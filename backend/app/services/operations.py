"""OPERATIONS — the COO's exception list (2026-09-02).

The COO does not live in task cards. This module turns the board, the client rollup, leave and the
engine's learning activity into a short list of EXCEPTIONS, each with an owner and one action, so
"what needs management attention today?" is answered in one screen. Anything not on the list is
running normally by construction.

Every line is derived from data other surfaces already keep honestly — nothing here has its own
store, and the thresholds are named constants the page prints.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import HOLD_KINDS, LEAVE_APPROVED, PRIORITY_URGENT, REVIEW_CHANGES, REVIEW_PENDING
from ..models import Client, LeaveRequest, Task, TaskHistory, User
from ..serializers import user_public
from ..utils.time import today_ph, utcnow
from . import client_health, task_analytics, task_config, task_perms, task_sessions
from . import team_growth

CLIENT_BLOCKED_DAYS = 2
REVIEW_STALE_HOURS = 24
REPEAT_CHANGES_DAYS = 30
STALLED_LEARNER_DAYS = 14
COVER_LOOKAHEAD_DAYS = 2
# The go-live reset (owner decision, 2026-09-02): the board was wiped and measurement starts
# from THIS day. The stalled-learner flag reads a trailing window, so until the window fits
# entirely after the baseline a quiet fortnight is a fact about the old era, not the new
# system - no learner exception is raised before then. Engine PROGRESS was deliberately NOT
# reset; only the measurement clock starts over.
MEASUREMENT_BASELINE = __import__('datetime').date(2026, 9, 2)


def _exc(sev: str, title: str, detail: str, owner: User | None, action: str, href: str, kind: str) -> dict:
    return {"severity": sev, "kind": kind, "title": title, "detail": detail,
            "owner": user_public(owner), "action": action, "href": href}


def capacity_rows(db: Session, viewer: User) -> list[dict]:
    """Per active person: open cards, overdue, estimated minutes on open cards, this week's session
    minutes, the Monitor's relative band, and leave — the COO's capacity table."""
    today = today_ph()
    users = db.execute(select(User).where(User.is_active.is_(True), User.role != "viewer")
                       .order_by(User.name)).scalars().all()
    tasks = db.execute(select(Task).where(Task.archived.is_(False))).scalars().all()
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}
    open_ts = [t for t in tasks if stage_of.get(t.status) != "completed"]
    monday = today - timedelta(days=today.weekday())
    frm, _ = task_sessions.day_bounds_utc(monday)
    _, to = task_sessions.day_bounds_utc(today)
    week_minutes = task_sessions.minutes_by_user(db, [u.id for u in users], frm, to)
    leave = task_analytics.leave_context(db, [u.id for u in users], today)
    rows = []
    for u in users:
        mine = [t for t in open_ts if u.id in task_perms.assigned_user_ids(t)]
        rows.append({
            "user": user_public(u),
            "stage": getattr(u, "stage", None),
            "open_total": len(mine),
            "overdue": len([t for t in mine if t.due_date and t.due_date < today
                            and stage_of.get(t.status) != "blocked"]),
            "estimate_minutes": sum(int(getattr(t, "estimate_minutes", 0) or 0) for t in mine),
            "estimated_cards": len([t for t in mine if getattr(t, "estimate_minutes", None)]),
            "week_minutes": week_minutes.get(u.id, 0),
            "on_leave_today": bool((leave.get(u.id) or {}).get("on_leave_today")),
            "leave_days_ahead": (leave.get(u.id) or {}).get("leave_days_ahead", 0),
        })
    task_analytics.apply_load_bands(rows)
    rows.sort(key=lambda r: (-r["open_total"], r["user"]["name"] if r["user"] else ""))
    return rows


def exceptions(db: Session, viewer: User) -> dict:
    today = today_ph()
    now = utcnow()
    out: list[dict] = []
    clients = client_health.rollup(db, viewer, today)
    tasks = db.execute(select(Task).where(Task.archived.is_(False))).scalars().all()
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in tasks}}
    open_ts = [t for t in tasks if stage_of.get(t.status) != "completed"]
    users = {u.id: u for u in db.execute(select(User)).scalars()}
    client_names = {c.id: c.name for c in db.execute(select(Client)).scalars()}

    # 1. Red clients
    for c in clients:
        if c["health"] == "red":
            am = users.get(c["account_manager_id"]) if c["account_manager_id"] else None
            out.append(_exc("red", f"{c['client']['name']} is red", " · ".join(c["why"]), am,
                            "Open client", f"/clients?client={c['client']['id']}", "client"))

    # 2. Overloaded people (the Monitor's relative band)
    cap = capacity_rows(db, viewer)
    for r in cap:
        if r.get("load_band") == "heavy":
            u = users.get(r["user"]["id"]) if r["user"] else None
            est = r["estimate_minutes"]
            detail = f"{r['open_total']} open cards"
            if est:
                detail += f" · ~{est // 60}h estimated"
            if r["overdue"]:
                detail += f" · {r['overdue']} overdue"
            out.append(_exc("red", f"{u.name if u else 'Someone'} is carrying more than the team",
                            detail, u, "Open Monitor", "/tasks?view=monitor", "overload"))

    # 3. Absence without cover — approved leave starting within 2 days while holding due-soon work
    horizon = today + timedelta(days=COVER_LOOKAHEAD_DAYS)
    leaves = db.execute(select(LeaveRequest).where(
        LeaveRequest.status == LEAVE_APPROVED, LeaveRequest.start_date <= horizon,
        LeaveRequest.end_date >= today)).scalars().all()
    for l in leaves:
        u = users.get(l.user_id)
        if not u:
            continue
        at_risk = [t for t in open_ts if t.assigned_to_id == u.id
                   and (t.priority == PRIORITY_URGENT or (t.due_date and t.due_date <= l.end_date))]
        if at_risk:
            names = ", ".join(t.title for t in at_risk[:2]) + (" …" if len(at_risk) > 2 else "")
            out.append(_exc("amber", f"{u.name} on leave {l.start_date:%b} {l.start_date.day}–{l.end_date:%b} {l.end_date.day}, holding due work",
                            f"{len(at_risk)} card(s) due while away: {names}", u,
                            "Open their board", f"/tasks?assignee_id={u.id}", "cover"))

    # 4. Waiting on a client for days
    parked_since = client_health.hold_since(db, open_ts)
    by_client: dict[int, list[Task]] = {}
    for t in open_ts:
        if stage_of.get(t.status) == "blocked" and getattr(t, "hold_kind", None) == "client":
            since = parked_since.get(t.id)
            if since and (now - since) >= timedelta(days=CLIENT_BLOCKED_DAYS):
                by_client.setdefault(t.client_id or 0, []).append(t)
    for cid, ts in by_client.items():
        oldest = min(parked_since[t.id] for t in ts)
        c = next((x for x in clients if x["client"]["id"] == cid), None)
        am = users.get(c["account_manager_id"]) if c and c["account_manager_id"] else None
        out.append(_exc("amber", f"{client_names.get(cid, 'A client')} hasn't answered for {(now - oldest).days} days",
                        " · ".join(t.title for t in ts[:3]), am, "Open client",
                        f"/clients?client={cid}", "client_blocked"))

    # 5. Reviews waiting more than a day
    reviewed_since = client_health.review_since(db, open_ts)
    stale = [t for t in open_ts if getattr(t, "review_state", None) == REVIEW_PENDING
             and (now - reviewed_since.get(t.id, now)) >= timedelta(hours=REVIEW_STALE_HOURS)]
    for t in stale:
        hours = int((now - reviewed_since[t.id]).total_seconds() // 3600)
        owner = users.get(t.account_manager_id) if t.account_manager_id else None
        out.append(_exc("amber", f"Review waiting {hours}h: {t.title}",
                        f"{client_names.get(t.client_id, 'Internal')} · submitted by "
                        f"{users[t.assigned_to_id].name if t.assigned_to_id in users else 'somebody'}",
                        owner, "Open task", f"/tasks?open={t.id}", "review"))

    # 6. Changes requested repeatedly on one person's work (a skill signal, not a task signal)
    since = now - timedelta(days=REPEAT_CHANGES_DAYS)
    rows = db.execute(select(TaskHistory.task_id).where(
        TaskHistory.field_changed == "review_state", TaskHistory.new_value == REVIEW_CHANGES,
        TaskHistory.changed_at >= since)).all()
    per_person: dict[int, int] = {}
    task_by_id = {t.id: t for t in tasks}
    for (tid,) in rows:
        t = task_by_id.get(tid)
        if t and t.assigned_to_id:
            per_person[t.assigned_to_id] = per_person.get(t.assigned_to_id, 0) + 1
    for uid, n in per_person.items():
        if n >= 2 and uid in users:
            out.append(_exc("grey", f"Changes requested {n}× on {users[uid].name}'s work this month",
                            "A pattern, not a task — tag the skill gap and assign training.", users[uid],
                            "Open profile", f"/people", "quality"))

    # 7. Stalled learners — fail-soft: the engine may be unreachable
    try:
        growth = team_growth.team_rows(db, viewer, days=STALLED_LEARNER_DAYS)
        # 🔴 An unreachable engine reports every row as zero activity. Zero is UNKNOWN then, not
        # "nobody trained" — the same rule team_growth itself prints — so no learner exception is
        # raised at all while `engine_error` is set. Only the workforce is measured: the roles that
        # hold live client work, not admins or the account managers.
        baseline_ready = (today - MEASUREMENT_BASELINE).days >= STALLED_LEARNER_DAYS
        if not growth.get("engine_error") and baseline_ready:
            for r in growth.get("rows") or []:
                if r.get("active_days") == 0 and r.get("attempts") == 0 and r.get("user"):
                    u = users.get(r["user"].get("id"))
                    if u and u.is_active and u.role in ("employee", "intern", "team_lead"):
                        out.append(_exc("grey", f"{u.name} has not trained in {STALLED_LEARNER_DAYS} days",
                                        "No Mastery Engine activity in the window.", u,
                                        "Open growth", f"/growth?user={u.id}", "learning"))
    except Exception:      # noqa: BLE001
        pass

    order = {"red": 0, "amber": 1, "grey": 2}
    out.sort(key=lambda e: order.get(e["severity"], 3))
    overdue = [t for t in open_ts if t.due_date and t.due_date < today and stage_of.get(t.status) != "blocked"]
    blocked = [t for t in open_ts if stage_of.get(t.status) == "blocked"]
    reviews = [t for t in open_ts if getattr(t, "review_state", None) == REVIEW_PENDING]
    return {
        "generated_at": now.isoformat() + "Z",
        "exceptions": out,
        "stats": {
            "clients_red": len([c for c in clients if c["health"] == "red"]),
            "clients_amber": len([c for c in clients if c["health"] == "amber"]),
            "clients_green": len([c for c in clients if c["health"] == "green"]),
            "overdue": len(overdue),
            "oldest_overdue_days": max([(today - t.due_date).days for t in overdue], default=0),
            "blocked": len(blocked),
            "blocked_on_client": len([t for t in blocked if getattr(t, "hold_kind", None) == "client"]),
            "blocked_on_us": len([t for t in blocked if getattr(t, "hold_kind", None) != "client"]),
            "reviews": len(reviews),
            "reviews_stale": len(stale),
            "heavy": len([r for r in cap if r.get("load_band") == "heavy"]),
        },
        "clients": clients,
        "capacity": cap,
        "thresholds": {"client_blocked_days": CLIENT_BLOCKED_DAYS, "review_stale_hours": REVIEW_STALE_HOURS,
                       "repeat_changes_days": REPEAT_CHANGES_DAYS, "stalled_learner_days": STALLED_LEARNER_DAYS},
        "hold_kinds": HOLD_KINDS,
    }
