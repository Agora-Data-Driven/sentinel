"""Reports + CSV export. Every report accepts ?from=&to=&team_id=&export=csv."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ADMIN_ROLES,
    LEAVE_PENDING,
    ROLE_ACCOUNT_MANAGER,
    ROLE_TEAM_LEAD,
    TASK_COMPLETED,
)
from ..database import get_db
from ..models import (
    Client,
    DailyAttendanceSummary,
    GymLog,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Task,
    Team,
    User,
)
from ..security import get_current_user
from ..utils.csv_export import csv_response
from ..utils.time import to_ph, today_ph

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _fmt_dt(dt):
    return to_ph(dt).strftime("%H:%M") if dt else ""


def _team_name(db: Session, team_id):
    t = db.get(Team, team_id) if team_id else None
    return t.name if t else ""


def _require_access(user: User, report: str):
    admin = user.role in ADMIN_ROLES
    if report in {"attendance", "gym", "leave"} and not admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if report == "team" and not (admin or user.role == ROLE_ACCOUNT_MANAGER):
        raise HTTPException(status_code=403, detail="Admin/AM access required")
    if report == "overdue" and not (admin or user.role == ROLE_TEAM_LEAD):
        raise HTTPException(status_code=403, detail="Admin/Team Lead access required")
    # "tasks" is open to all (naturally filtered by visibility below).


def _build(db: Session, report: str, user: User, from_: date | None, to: date | None, team_id: int | None):
    if report == "attendance":
        q = select(DailyAttendanceSummary).order_by(DailyAttendanceSummary.date.desc())
        if from_:
            q = q.where(DailyAttendanceSummary.date >= from_)
        if to:
            q = q.where(DailyAttendanceSummary.date <= to)
        headers = ["Employee", "Date", "In", "Out", "Status", "Hours", "Handover"]
        rows = []
        for s in db.execute(q).scalars().all():
            u = db.get(User, s.user_id)
            if team_id and (not u or u.team_id != team_id):
                continue
            rows.append([u.name if u else "?", s.date.isoformat(), _fmt_dt(s.clock_in),
                         _fmt_dt(s.clock_out), s.status, s.total_work_hours,
                         (s.handover_note or "")[:120]])
        return headers, rows

    if report == "gym":
        q = select(GymLog).order_by(GymLog.date.desc())
        if from_:
            q = q.where(GymLog.date >= from_)
        if to:
            q = q.where(GymLog.date <= to)
        headers = ["Employee", "Date", "Day Type", "Duration (min)", "Status", "Exercises"]
        rows = []
        for g in db.execute(q).scalars().all():
            u = db.get(User, g.user_id)
            if team_id and (not u or u.team_id != team_id):
                continue
            rows.append([u.name if u else "?", g.date.isoformat(), g.day_type,
                         g.duration_minutes, g.status, len(g.exercises)])
        return headers, rows

    if report == "tasks":
        from ..services import task_perms  # centralized authorization (was tasks._can_view)
        q = select(Task).order_by(Task.due_date.is_(None), Task.due_date.asc())
        if team_id:
            q = q.where(Task.assigned_team_id == team_id)
        headers = ["Task", "Client", "Dept", "Priority", "Status", "Due", "Assignee"]
        rows = []
        for t in db.execute(q).scalars().all():
            if not task_perms.can_view(user, t):
                continue
            client = db.get(Client, t.client_id) if t.client_id else None
            assignee = db.get(User, t.assigned_to_id) if t.assigned_to_id else None
            rows.append([t.title, client.name if client else "", _team_name(db, t.assigned_team_id),
                         t.priority, t.status, t.due_date.isoformat() if t.due_date else "",
                         assignee.name if assignee else ""])
        return headers, rows

    if report == "team":
        headers = ["Team", "Done", "On-time %", "Avg days"]
        rows = []
        teams = db.execute(select(Team).order_by(Team.name)).scalars().all()
        for team in teams:
            if team_id and team.id != team_id:
                continue
            tasks = db.execute(select(Task).where(Task.assigned_team_id == team.id)).scalars().all()
            done = [t for t in tasks if t.status == TASK_COMPLETED]
            on_time = 0
            spans = []
            for t in done:
                if t.due_date and t.updated_at and to_ph(t.updated_at).date() <= t.due_date:
                    on_time += 1
                spans.append((to_ph(t.updated_at).date() - to_ph(t.created_at).date()).days)
            pct = round(100 * on_time / len(done), 1) if done else 0.0
            avg = round(sum(spans) / len(spans), 1) if spans else 0.0
            rows.append([team.name, len(done), pct, avg])
        return headers, rows

    if report == "leave":
        headers = ["Employee", "Type", "Used", "Remaining", "Pending"]
        rows = []
        year = today_ph().year
        balances = db.execute(select(LeaveBalance).where(LeaveBalance.year == year)).scalars().all()
        for b in balances:
            u = db.get(User, b.user_id)
            if team_id and (not u or u.team_id != team_id):
                continue
            lt = db.get(LeaveType, b.leave_type_id)
            pending = db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.user_id == b.user_id,
                    LeaveRequest.leave_type_id == b.leave_type_id,
                    LeaveRequest.status == LEAVE_PENDING,
                )
            ).scalars().all()
            rows.append([u.name if u else "?", lt.name if lt else "?", b.used,
                         "∞" if (lt and lt.annual_balance < 0) else b.remaining, len(pending)])
        return headers, rows

    if report == "overdue":
        headers = ["Task", "Days overdue", "Priority", "Assignee"]
        rows = []
        today = today_ph()
        q = select(Task).where(Task.due_date.is_not(None), Task.status != TASK_COMPLETED)
        if team_id:
            q = q.where(Task.assigned_team_id == team_id)
        for t in db.execute(q).scalars().all():
            if t.due_date and t.due_date < today:
                if user.role == ROLE_TEAM_LEAD and t.assigned_team_id != user.team_id:
                    continue
                assignee = db.get(User, t.assigned_to_id) if t.assigned_to_id else None
                rows.append([t.title, (today - t.due_date).days, t.priority,
                             assignee.name if assignee else ""])
        rows.sort(key=lambda r: r[1], reverse=True)
        return headers, rows

    raise HTTPException(status_code=404, detail="Unknown report type")


@router.get("/{report}")
def report(
    report: str,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    team_id: int | None = Query(None),
    export: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_access(user, report)
    headers, rows = _build(db, report, user, from_, to, team_id)
    if export == "csv":
        return csv_response(f"sentinel-{report}-{today_ph().isoformat()}.csv", headers, rows)
    return {"report": report, "columns": headers, "rows": rows, "count": len(rows)}
