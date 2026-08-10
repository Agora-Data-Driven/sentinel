"""Daily auto-processing — the job that runs once a day (Cloud Scheduler) so attendance and
reminders don't depend on anyone remembering to click.

For the target day (default: yesterday, PH time) on a working day it:
  - rebuilds each active employee's attendance summary (creating an **Absent** row for no-shows,
    **MissingClockOut** for forgot-to-clock-out, or the normal On-time/Late),
  - reclassifies would-be-absent people who are on **approved leave** as OnLeave,
  - nudges anyone who forgot to clock out.
Then, independent of the day, it posts aggregate reminders: overdue tasks (to each assignee) and
pending approvals (to managers). Everything is idempotent — safe to run twice.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    LEAVE_APPROVED,
    LEAVE_PENDING,
    REQ_PENDING,
    STATUS_ABSENT,
    STATUS_MISSING_CLOCKOUT,
    STATUS_ON_LEAVE,
    TASK_COMPLETED,
)
from ..models import AttendanceRequest, DailyAttendanceSummary, LeaveRequest, Task, User
from . import notifications as notif
from . import settings as settings_svc
from .attendance import recompute_summary
from ..utils.time import today_ph

_WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _workdays(smap: dict) -> set[int]:
    days = {_WD[d.strip().lower()[:3]] for d in smap.get("work_days", "Mon,Tue,Wed,Thu,Fri").split(",")
            if d.strip()[:3].lower() in _WD}
    return days or {0, 1, 2, 3, 4}


def _on_leave_ids(db: Session, day: date) -> set[int]:
    rows = db.execute(
        select(LeaveRequest.user_id).where(
            LeaveRequest.status == LEAVE_APPROVED,
            LeaveRequest.start_date <= day,
            LeaveRequest.end_date >= day,
        )
    ).all()
    return {r[0] for r in rows}


def process_attendance(db: Session, day: date) -> dict:
    smap = settings_svc.get_map(db)
    result = {"date": day.isoformat(), "workday": day.weekday() in _workdays(smap),
              "absent": 0, "on_leave": 0, "missing_clockout": 0, "present": 0}
    if not result["workday"]:
        return result  # attendance not expected on a rest day

    users = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    on_leave = _on_leave_ids(db, day)
    for u in users:
        s = recompute_summary(db, u, day, commit=False)
        if s.status == STATUS_ABSENT and u.id in on_leave:
            s.status = STATUS_ON_LEAVE
            result["on_leave"] += 1
        elif s.status == STATUS_ABSENT:
            result["absent"] += 1
        elif s.status == STATUS_MISSING_CLOCKOUT:
            result["missing_clockout"] += 1
            notif.notify(db, user_id=u.id, type="attendance",
                         title="You forgot to clock out",
                         body=f"No clock-out recorded for {day.isoformat()}. Submit a regularization if needed.",
                         link="/attendance", commit=False)
        else:
            result["present"] += 1
    return result


def send_reminders(db: Session) -> dict:
    """Aggregate nudges: overdue tasks (per assignee) + pending approvals (to managers)."""
    today = today_ph()
    result = {"overdue_notified": 0, "pending_approvals": 0}

    # Overdue tasks -> one summary notification per assignee (no per-task spam).
    overdue = db.execute(
        select(Task).where(
            Task.due_date.is_not(None), Task.due_date < today,
            Task.status != TASK_COMPLETED, Task.assigned_to_id.is_not(None),
        )
    ).scalars().all()
    by_user: dict[int, int] = {}
    for t in overdue:
        by_user[t.assigned_to_id] = by_user.get(t.assigned_to_id, 0) + 1
    for uid, n in by_user.items():
        notif.notify(db, user_id=uid, type="task_overdue",
                     title=f"{n} task{'s' if n != 1 else ''} overdue",
                     body="You have work past its due date. Update or reschedule it.",
                     link="/dashboard", commit=False)
        result["overdue_notified"] += 1

    # Pending approvals -> managers.
    pend_leave = db.execute(select(LeaveRequest).where(LeaveRequest.status == LEAVE_PENDING)).scalars().all()
    pend_att = db.execute(select(AttendanceRequest).where(AttendanceRequest.status == REQ_PENDING)).scalars().all()
    total = len(pend_leave) + len(pend_att)
    if total:
        notif.notify_managers(db, type="approval",
                              title=f"{total} request{'s' if total != 1 else ''} awaiting review",
                              body=f"{len(pend_leave)} leave · {len(pend_att)} attendance. Review them in the app.",
                              link="/leave", commit=False)
        result["pending_approvals"] = total
    return result


def mirror_clients(db: Session) -> dict:
    """Pull Atrium's client registry. Additive-only, fail-soft. Part of the daily pass.

    🔴 THE MIRROR USED TO BE BOOT-ONLY, AND THAT STOPPED WORKING ON 2026-08-07. A client created in
    Atrium reaches Sentinel's `clients` table — which is what feeds the New Task picker and the
    board's client filter — only when `client_sync.sync` runs, and its only automatic trigger was
    `main._mirror_clients` at boot. That was survivable while Cloud Run scaled to ZERO: any quiet
    spell ended in a fresh boot, so a new client appeared on its own within about fifteen minutes.
    Adding `--min-instances 1` the same day removed those restarts, so "boot-only" became "once" and
    a new client could stay invisible here indefinitely. Confirmed live: a client added minutes after
    a deploy was still absent hours later, with the boot log showing a healthy `created: 0` sync.

    🔴 `deactivate` is NOT passed, so it stays False. Deactivation is driven by ABSENCE, and absence
    is a lie whenever the two systems spell a client differently — a scheduled job is the LAST place
    that should act on it, because nobody is watching when it runs. Retiring a client stays the
    deliberate two-step in AGENTS.md §2: read `sync-preview`, then `sync?deactivate=1` by hand.

    Fail-soft, and returned rather than raised: this runs after the attendance pass has committed, and
    an Atrium outage must not take the daily job — or its already-written work — down with it.

    🔴 **This does not fire yet in production.** Nothing schedules `POST /api/cron/daily` (verified
    2026-08-07: no Cloud Scheduler job in any region, no in-app scheduler, and `CRON_KEY` unset on the
    service, so only a Super Admin session can reach the route). Until that is wired up, the reliable
    trigger is the **Sync now** button in Manage → Clients. See AGENTS.md §2.
    """
    from . import client_sync

    try:
        report = client_sync.sync(db)
    except Exception as exc:                     # noqa: BLE001 — see the docstring
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    # `client_sync.sync` already refuses to act on an empty or failed answer; surface that verdict
    # instead of flattening it, so a silent no-op and a real refusal are distinguishable in the log.
    return {k: report.get(k) for k in ("ok", "error", "created", "updated", "linked",
                                       "would_deactivate") if k in report}


def publish_report(db: Session) -> dict:
    """Regenerate the personal context report and replace its Google Doc.

    OFF unless both `report_doc_id` and `report_user_email` are set, so every other estate — and
    every developer running the daily pass locally — is unaffected by default.

    🔴 Fail-soft, like `mirror_clients`: this runs after the attendance pass has committed, and a
    Drive outage must not take the daily job (or its already-written work) down with it. But the
    verdict is RETURNED, not swallowed — the document is this job's only output, and a silent
    failure leaves yesterday's text in place looking current. `report_doc.publish` is deliberately
    not fail-soft internally for the same reason.
    """
    from ..config import settings

    doc_id = (settings.report_doc_id or "").strip()
    email = (settings.report_user_email or "").strip().lower()
    if not doc_id or not email:
        return {"ok": None, "skipped": "not configured"}

    from sqlalchemy import func

    from . import personal_report, report_doc

    user = db.execute(select(User).where(func.lower(User.email) == email)).scalars().first()
    if user is None:
        return {"ok": False, "error": f"{email} is not a Sentinel user"}
    if not user.is_active:
        return {"ok": False, "error": f"{email} is not active"}

    try:
        built = personal_report.build(db, user)
    except Exception as exc:                      # noqa: BLE001 — see the docstring
        return {"ok": False, "error": f"building the report failed ({type(exc).__name__}: {exc})"}

    result = report_doc.publish(built["markdown"], doc_id)
    # `gaps` travels with the verdict so a caller can see that the document published fine while
    # still being short of a source — "it worked" and "it was complete" are different questions.
    return {"ok": result.get("ok"), "error": result.get("error") or "",
            "bytes": result.get("bytes"), "chars": len(built["markdown"]),
            "gaps": built.get("gaps") or []}


def run(db: Session, day: date | None = None) -> dict:
    """Full daily pass. ``day`` defaults to yesterday (PH). Commits once at the end."""
    target = day or (today_ph() - timedelta(days=1))
    att = process_attendance(db, target)
    rem = send_reminders(db)
    db.commit()

    # Clients BEFORE recurring work, deliberately: a retainer deliverable hangs off a Sentinel
    # `Client` row, so syncing first means a workspace created in Atrium today can already receive
    # its recurrence on this same pass instead of waiting for tomorrow's.
    clients = mirror_clients(db)

    # Retainer deliverables (WP 6.1). 🔴 Generated against TODAY, not `target`: the attendance pass
    # deliberately processes YESTERDAY (a day is only complete once it has ended), but a recurring
    # task must appear on the day it is due, and running it a day behind would put every monthly
    # deliverable on the board one day late — and, on the 1st, in the previous month's period.
    # Safe to run repeatedly: each recurrence claims its period, so a second tick creates nothing.
    from . import task_recurring
    made = task_recurring.run(db, today_ph())

    # LAST, deliberately: the report reads the state every step above has just written (recurring
    # deliverables land on the board, the client mirror renames a workspace), so publishing before
    # them would ship a document a few minutes out of date on its own run.
    report = publish_report(db)

    return {"ok": True, "attendance": att, "reminders": rem, "recurring": made,
            "clients": clients, "report": report}
