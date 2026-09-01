"""The CALENDAR — a projection of dated records, not a table (2026-09-02).

There is deliberately no `calendar_events` table. Every event here is derived, on read, from a
record that already carries a date: a task's due date, a recurring service's next trigger day, an
approved leave request. Change the due date on the card and the calendar moves; nothing has to be
kept in step. (Client meetings and report dates live in Atrium's `calendar[]`; adding them is one
more internal read, not a new store.)

Scope follows the board: a task appears only if `task_perms.can_view` says so, and `mine=True`
narrows to `is_assigned` — the same two predicates the Task Board and the Overview use, never a
third copy.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import LEAVE_APPROVED, ROLE_TEAM_LEAD
from ..models import Client, LeaveRequest, RecurringService, Task, User
from ..serializers import user_public
from ..utils.time import today_ph
from . import task_config, task_perms, task_recurring
from . import teams as teams_svc

MAX_DAYS = 62


def _clamp(frm: date, to: date) -> tuple[date, date]:
    if to < frm:
        frm, to = to, frm
    if (to - frm).days > MAX_DAYS:
        to = frm + timedelta(days=MAX_DAYS)
    return frm, to


def events(db: Session, viewer: User, frm: date, to: date, mine: bool = False) -> dict:
    frm, to = _clamp(frm, to)
    today = today_ph()
    out: list[dict] = []

    # --- tasks: due dates (open → "due", finished → "done") ------------------------------------
    tasks = db.execute(
        select(Task).where(Task.archived.is_(False), Task.due_date.is_not(None),
                           Task.due_date >= frm, Task.due_date <= to)
    ).scalars().all()
    visible = [t for t in tasks if task_perms.can_view(viewer, t)
               and (not mine or task_perms.is_assigned(viewer, t))]
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in visible}}
    client_ids = {t.client_id for t in visible if t.client_id}
    clients = {c.id: c.name for c in db.execute(select(Client).where(Client.id.in_(client_ids or [-1]))).scalars()}
    user_ids = {t.assigned_to_id for t in visible if t.assigned_to_id}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids or [-1]))).scalars()}
    for t in visible:
        stage = stage_of.get(t.status)
        done = stage == "completed"
        out.append({
            "kind": "done" if done else "due",
            "date": t.due_date.isoformat(),
            "title": t.title,
            "task_id": t.id,
            "client": clients.get(t.client_id),
            "assignee": user_public(users.get(t.assigned_to_id)),
            "late": (not done and stage != "blocked" and t.due_date < today),
            "parked": stage == "blocked",
            "priority": t.priority,
            "href": f"/tasks?open={t.id}",
        })

    # --- recurring services: the days they will fire in the window ---------------------------
    recs = db.execute(select(RecurringService).where(RecurringService.is_active.is_(True))).scalars().all()
    if recs and (not mine or True):
        d = frm
        while d <= to:
            for r in recs:
                if mine and r.assigned_to_id not in (None, viewer.id):
                    continue
                try:
                    fires = task_recurring.trigger_day(r, d) == d
                except Exception:      # noqa: BLE001 — a bad recurrence must not blank the calendar
                    fires = False
                if fires and d >= today:
                    out.append({
                        "kind": "recurring",
                        "date": d.isoformat(),
                        "title": r.title,
                        "recurring_id": r.id,
                        "client": clients.get(r.client_id) or _client_name(db, r.client_id),
                        "assignee": user_public(users.get(r.assigned_to_id) or _user(db, r.assigned_to_id)),
                        "href": "/tasks",
                    })
            d += timedelta(days=1)

    # --- approved leave: own always; everyone's for a lead/manager ---------------------------
    leave_q = select(LeaveRequest).where(LeaveRequest.status == LEAVE_APPROVED,
                                         LeaveRequest.end_date >= frm, LeaveRequest.start_date <= to)
    is_manager = viewer.role in task_perms.FULL or viewer.role == ROLE_TEAM_LEAD or viewer.role == "viewer"
    if mine or not is_manager:
        leave_q = leave_q.where(LeaveRequest.user_id == viewer.id)
    leaves = db.execute(leave_q).scalars().all()
    lusers = {u.id: u for u in db.execute(select(User).where(
        User.id.in_({l.user_id for l in leaves} or [-1]))).scalars()}
    if viewer.role == ROLE_TEAM_LEAD and not mine:
        # A lead sees their departments' leave, not the whole company's.
        mine_teams = set(teams_svc.team_ids(viewer))
        leaves = [l for l in leaves if lusers.get(l.user_id) and
                  (lusers[l.user_id].id == viewer.id or set(teams_svc.team_ids(lusers[l.user_id])) & mine_teams)]
    for l in leaves:
        u = lusers.get(l.user_id)
        out.append({
            "kind": "leave",
            "date": max(l.start_date, frm).isoformat(),
            "end_date": min(l.end_date, to).isoformat(),
            "title": f"{u.name if u else 'Someone'} on leave",
            "assignee": user_public(u),
            "href": "/leave",
        })

    out.sort(key=lambda e: (e["date"], e["kind"] != "due", e.get("title") or ""))
    return {"from": frm.isoformat(), "to": to.isoformat(), "today": today.isoformat(), "events": out}


def _client_name(db: Session, cid: int | None) -> str | None:
    if not cid:
        return None
    c = db.get(Client, cid)
    return c.name if c else None


def _user(db: Session, uid: int | None) -> User | None:
    return db.get(User, uid) if uid else None
