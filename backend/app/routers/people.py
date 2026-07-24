"""People (employee directory + profiles), QR badge generation."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ALL_ROLES,
    LEAVE_APPROVED,
    ROLE_LABELS,
    ROLE_TEAM_LEAD,
    ROLE_SUPER_ADMIN,
)
from ..database import get_db
from ..models import (
    AttendanceEvent,
    AttendanceRequest,
    AuditLog,
    DailyAttendanceSummary,
    GymExercise,
    GymLog,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Notification,
    QRToken,
    SystemSetting,
    Task,
    TaskComment,
    TaskHistory,
    Team,
    User,
)
from ..schemas import PersonCreateIn, PersonUpdateIn
from ..security import get_current_user, is_admin, require_min_role, require_roles
from ..serializers import gym_log_dict, leave_balance_dict, summary_dict, task_card, user_full
from ..services import audit
from ..services import leave as leave_svc
from ..utils.time import normalize_hhmm, today_ph, utcnow
from ..utils.qr import make_qr_png, new_token
from ..utils.passwords import hash_password


def _norm_shift(v: str | None) -> str | None:
    """None/blank -> None (inherit team/default); otherwise validate + normalize to 'HH:MM'."""
    if v in (None, ""):
        return None
    try:
        return normalize_hhmm(str(v))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

router = APIRouter(prefix="/api/people", tags=["people"])


def _status_of(db: Session, user: User) -> str:
    if not user.is_active:
        return "Inactive"
    today = today_ph()
    on_leave = db.execute(
        select(LeaveRequest).where(
            LeaveRequest.user_id == user.id,
            LeaveRequest.status == LEAVE_APPROVED,
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today,
        )
    ).first()
    return "On Leave" if on_leave else "Active"


@router.get("")
def directory(
    team: int | None = Query(None),
    role: str | None = Query(None),
    search: str | None = Query(None),
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(User).order_by(User.name)).scalars().all()
    out = []
    for u in rows:
        if team and u.team_id != team:
            continue
        if role and u.role != role:
            continue
        if search:
            s = search.lower()
            if s not in u.name.lower() and s not in u.email.lower():
                team_obj = db.get(Team, u.team_id) if u.team_id else None
                if not (team_obj and s in team_obj.name.lower()):
                    continue
        st = _status_of(db, u)
        if status and st != status:
            continue
        team_obj = db.get(Team, u.team_id) if u.team_id else None
        d = user_full(u, team_obj)
        d["status"] = st
        out.append(d)
    return out


@router.get("/{user_id}")
def profile(user_id: int, viewer: User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    team = db.get(Team, u.team_id) if u.team_id else None
    profile = user_full(u, team)
    profile["status"] = _status_of(db, u)

    today = today_ph()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    att_rows = db.execute(
        select(DailyAttendanceSummary).where(
            DailyAttendanceSummary.user_id == u.id, DailyAttendanceSummary.date >= month_start
        ).order_by(DailyAttendanceSummary.date.desc())
    ).scalars().all()
    attendance = {
        "days": len(att_rows),
        "on_time": sum(1 for s in att_rows if s.status == "OnTime"),
        "late": sum(1 for s in att_rows if s.status == "Late"),
        "absent": sum(1 for s in att_rows if s.status == "Absent"),
        "total_hours": round(sum(s.total_work_hours for s in att_rows), 1),
        "recent": [summary_dict(s, u) for s in att_rows[:7]],
    }

    gym_rows = db.execute(
        select(GymLog).where(GymLog.user_id == u.id, GymLog.date >= week_start)
    ).scalars().all()
    gym = {
        "sessions": len(gym_rows),
        "completed": sum(1 for g in gym_rows if g.status == "Completed"),
        "recent": [gym_log_dict(g, db) for g in gym_rows],
    }

    tasks = db.execute(
        select(Task).where(Task.assigned_to_id == u.id, Task.status != "Completed")
    ).scalars().all()

    year = today.year
    leave_svc.ensure_balances(db, u.id, year)
    balances = db.execute(
        select(LeaveBalance).where(LeaveBalance.user_id == u.id, LeaveBalance.year == year)
    ).scalars().all()

    return {
        "profile": profile,
        "attendance": attendance,
        "gym": gym,
        "tasks": [task_card(t, db) for t in tasks],
        "leave_balances": [
            leave_balance_dict(b, db.get(LeaveType, b.leave_type_id)) for b in balances
        ],
    }


@router.post("", dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN))])
def create_person(payload: PersonCreateIn, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    email = payload.email.strip().lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists")
    u = User(
        name=payload.name, email=email, role=payload.role, team_id=payload.team_id,
        phone=payload.phone, hired_date=payload.hired_date,
        shift_template_id=payload.shift_template_id,
        shift_start=_norm_shift(payload.shift_start), shift_end=_norm_shift(payload.shift_end),
    )
    if payload.password:
        u.password_hash = hash_password(payload.password)
    db.add(u)
    db.flush()
    db.add(QRToken(user_id=u.id, token=new_token()))
    leave_svc.ensure_balances(db, u.id, today_ph().year, commit=False)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="users", record_id=u.id, action="create",
                 new={"email": u.email, "role": u.role})
    team = db.get(Team, u.team_id) if u.team_id else None
    return user_full(u, team)


@router.patch("/{user_id}")
def update_person(user_id: int, payload: PersonUpdateIn, actor: User = Depends(require_min_role("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in ALL_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    for k in ("shift_start", "shift_end"):  # validate/normalize times; blank clears the override
        if k in data:
            data[k] = _norm_shift(data[k])
    # Password is set separately (hashed), and never echoed in the audit log.
    new_password = data.pop("password", None)
    if new_password:
        u.password_hash = hash_password(new_password)
    if "email" in data and data["email"]:
        data["email"] = data["email"].strip().lower()
    before = {k: getattr(u, k) for k in data}
    for field, value in data.items():
        setattr(u, field, value)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="users", record_id=u.id, action="update",
                 old=before, new={**data, **({"password": "***"} if new_password else {})})
    team = db.get(Team, u.team_id) if u.team_id else None
    return user_full(u, team)


@router.get("/{user_id}/qr")
def qr_badge(user_id: int, actor: User = Depends(require_min_role("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    token_row = db.execute(
        select(QRToken).where(QRToken.user_id == u.id, QRToken.is_active.is_(True))
    ).scalar_one_or_none()
    if not token_row:
        token_row = QRToken(user_id=u.id, token=new_token())
        db.add(token_row)
        db.commit()
    png = make_qr_png(token_row.token)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="badge-{u.id}.png"'},
    )


@router.get("/{user_id}/badge")
def badge_code(user_id: int, actor: User = Depends(require_min_role("admin")), db: Session = Depends(get_db)):
    """The employee's badge CODE (the same token the QR encodes) — for typing when they can't scan,
    or to re-give if they lost their badge. Admin+ only (a token can punch that person's attendance)."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    token_row = db.execute(
        select(QRToken).where(QRToken.user_id == u.id, QRToken.is_active.is_(True))
    ).scalar_one_or_none()
    if not token_row:
        token_row = QRToken(user_id=u.id, token=new_token())
        db.add(token_row)
        db.commit()
    return {"user_id": u.id, "name": u.name, "code": token_row.token}


@router.post("/{user_id}/qr/regenerate")
def regenerate_qr(user_id: int, actor: User = Depends(require_min_role("admin")), db: Session = Depends(get_db)):
    """Issue a fresh QR token for an employee (revokes the old one). Assigns it to that employee."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    db.query(QRToken).filter(QRToken.user_id == u.id, QRToken.is_active.is_(True)).update(
        {QRToken.is_active: False, QRToken.revoked_at: utcnow()}, synchronize_session=False
    )
    tok = QRToken(user_id=u.id, token=new_token())
    db.add(tok)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="qr_tokens", record_id=tok.id,
                 action="regenerate", new={"user_id": u.id})
    return {"ok": True, "user_id": u.id}


@router.delete("/{user_id}", dependencies=[Depends(require_roles(ROLE_SUPER_ADMIN))])
def delete_person(user_id: int, actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently remove an employee and clean up their dependent records.

    Super Admin only. Refuses to delete yourself. Attendance/gym/leave/notifications owned by the
    user are deleted; task ownership + audit/history references are nulled out so nothing breaks.
    (To keep history instead, edit the employee and set status = Inactive.)
    """
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    if u.id == actor.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account")

    name = u.name
    # Owned records -> delete.
    db.query(AttendanceEvent).filter(AttendanceEvent.user_id == u.id).delete(synchronize_session=False)
    db.query(DailyAttendanceSummary).filter(DailyAttendanceSummary.user_id == u.id).delete(synchronize_session=False)
    db.query(AttendanceRequest).filter(AttendanceRequest.user_id == u.id).delete(synchronize_session=False)
    db.query(LeaveBalance).filter(LeaveBalance.user_id == u.id).delete(synchronize_session=False)
    db.query(LeaveRequest).filter(LeaveRequest.user_id == u.id).delete(synchronize_session=False)
    gym_ids = [g.id for g in db.query(GymLog.id).filter(GymLog.user_id == u.id).all()]
    if gym_ids:
        db.query(GymExercise).filter(GymExercise.gym_log_id.in_(gym_ids)).delete(synchronize_session=False)
    db.query(GymLog).filter(GymLog.user_id == u.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == u.id).delete(synchronize_session=False)
    db.query(TaskComment).filter(TaskComment.author_id == u.id).delete(synchronize_session=False)
    db.query(QRToken).filter(QRToken.user_id == u.id).delete(synchronize_session=False)
    # References from other people's records -> null out (keep those records intact).
    db.query(AttendanceRequest).filter(AttendanceRequest.reviewed_by_id == u.id).update({AttendanceRequest.reviewed_by_id: None}, synchronize_session=False)
    db.query(LeaveRequest).filter(LeaveRequest.reviewed_by_id == u.id).update({LeaveRequest.reviewed_by_id: None}, synchronize_session=False)
    db.query(TaskHistory).filter(TaskHistory.changed_by_id == u.id).update({TaskHistory.changed_by_id: None}, synchronize_session=False)
    db.query(Task).filter(Task.assigned_to_id == u.id).update({Task.assigned_to_id: None}, synchronize_session=False)
    db.query(Task).filter(Task.account_manager_id == u.id).update({Task.account_manager_id: None}, synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.actor_id == u.id).update({AuditLog.actor_id: None}, synchronize_session=False)
    db.query(SystemSetting).filter(SystemSetting.updated_by_id == u.id).update({SystemSetting.updated_by_id: None}, synchronize_session=False)

    db.delete(u)
    db.commit()
    audit.record(db, actor_id=actor.id, table_name="users", record_id=user_id, action="delete",
                 old={"name": name})
    return {"ok": True}
