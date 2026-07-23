"""Gym Tracker: always-editable sessions, Hevy-style exercise logging, the weekly plan +
calendar, exercise library, and compliance."""
from __future__ import annotations

import calendar as _calendar
import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    DAY_REST,
    GYM_DAY_TYPES,
    GYM_PLAN_DAY_TYPES,
    GYM_WEEKDAYS,
    ROLE_SUPER_ADMIN,
    ROLE_TEAM_LEAD,
)
from ..database import get_db
from ..models import ExerciseLibrary, GymExercise, GymLog, User
from ..schemas import (
    GymAdminEditIn,
    GymDayOpenIn,
    GymExerciseIn,
    GymPlanDayIn,
    GymPlanWeekIn,
    GymSessionEditIn,
)
from ..security import get_current_user, require_min_role, require_roles
from ..serializers import gym_log_dict
from ..services import audit
from ..services import gym as gym_svc
from ..services import settings as settings_svc
from ..utils.time import today_ph, utcnow

router = APIRouter(prefix="/api/gym", tags=["gym"])


def _required_hours(db: Session) -> float:
    return float(settings_svc.get(db, "gym_required_hours") or "1")


def _recompute(log: GymLog, db: Session) -> None:
    """Auto-derive compliance status from the (user-owned) duration + logged exercises. No lock:
    the session stays editable forever, but the manager compliance view still gets a live status."""
    log.status = gym_svc.compute_status(log.duration_minutes or 0, len(log.exercises), _required_hours(db))


@router.post("/day")
def open_day(payload: GymDayOpenIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open (or create) the editable session for a date — no start/finish lock. The day-type
    defaults to whatever the weekly plan says for that date; the user can override it here."""
    day = payload.date or today_ph()
    day_type = payload.day_type or gym_svc.effective_plan(db, user.id, day)
    if day_type == DAY_REST:
        day_type = "Custom"  # you can always train on a planned rest day; just don't force "Rest"
    if day_type not in GYM_DAY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid day type")
    log = db.execute(
        select(GymLog).where(GymLog.user_id == user.id, GymLog.date == day)
    ).scalar_one_or_none()
    if not log:
        log = GymLog(user_id=user.id, date=day, day_type=day_type, start_time=utcnow())
        db.add(log)
    elif payload.day_type:
        log.day_type = day_type
    log.start_time = log.start_time or utcnow()
    _recompute(log, db)
    db.commit()
    return gym_log_dict(log, db, with_exercises=True)


@router.patch("/{log_id}/session")
def edit_session(
    log_id: int,
    payload: GymSessionEditIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The owner's no-lock edits to their session: day-type, duration, notes, and a soft 'done'
    marker. Editable at any time — 'done' never freezes the session, it's just a tidy-up flag."""
    log = db.get(GymLog, log_id)
    if not log or log.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    if payload.day_type is not None:
        if payload.day_type not in GYM_DAY_TYPES:
            raise HTTPException(status_code=400, detail="Invalid day type")
        log.day_type = payload.day_type
    if payload.duration_minutes is not None:
        log.duration_minutes = max(0, payload.duration_minutes)
    if payload.notes is not None:
        log.notes = payload.notes
    if payload.done is not None:
        # 'Done' just stamps an end_time for the record; clearing it reopens the timer.
        log.end_time = utcnow() if payload.done else None
    _recompute(log, db)
    db.commit()
    return {"log": gym_log_dict(log, db, with_exercises=True), "summary": gym_svc.session_summary(log)}


@router.post("/{log_id}/exercises")
def save_exercises(
    log_id: int,
    payload: list[GymExerciseIn],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the session's exercise set with the submitted list (idempotent save)."""
    log = db.get(GymLog, log_id)
    if not log or log.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    for ex in list(log.exercises):
        db.delete(ex)
    db.flush()
    for e in payload:
        sets_detail = [s.model_dump() for s in e.sets_detail]
        # Derive the "top set" summary columns from the per-set detail when present.
        sets = len(sets_detail) or e.sets
        top_kg = max((s.get("kg", 0) for s in sets_detail), default=e.weight_value)
        top_reps = max((s.get("reps", 0) for s in sets_detail), default=e.reps)
        db.add(
            GymExercise(
                gym_log_id=log.id,
                exercise_name=e.exercise_name,
                muscle_group=e.muscle_group,
                weight_value=top_kg or 0,
                weight_unit=e.weight_unit,
                sets=sets,
                reps=top_reps or 0,
                set_type=e.set_type,
                sets_json=json.dumps(sets_detail),
                duration_minutes=e.duration_minutes,
                notes=e.notes,
            )
        )
    db.flush()
    _recompute(log, db)
    db.commit()
    db.refresh(log)
    return gym_log_dict(log, db, with_exercises=True)


@router.get("/library")
def library(
    day_type: str | None = Query(None),
    q: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(ExerciseLibrary).order_by(ExerciseLibrary.name)).scalars().all()
    out = []
    for e in rows:
        try:
            days = json.loads(e.day_types_json or "[]")
        except (ValueError, TypeError):
            days = []
        if day_type and day_type not in days:
            continue
        if q and q.lower() not in e.name.lower():
            continue
        out.append(
            {
                "id": e.id,
                "name": e.name,
                "muscle_group": e.muscle_group,
                "day_types": days,
                "equipment": e.equipment,
                "instructions": e.instructions,
                "previous": gym_svc.previous_for_exercise(db, user.id, e.name, today_ph()),
            }
        )
    return out


@router.get("/my")
def my_gym(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(GymLog).where(GymLog.user_id == user.id).order_by(GymLog.date.desc())
    ).scalars().all()
    return [gym_log_dict(g, db) for g in rows]


@router.get("/today")
def today_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = db.execute(
        select(GymLog).where(GymLog.user_id == user.id, GymLog.date == today_ph())
    ).scalar_one_or_none()
    return gym_log_dict(log, db, with_exercises=True) if log else None


# --- Weekly plan (the calendar's forward schedule) -------------------------

@router.get("/plan")
def get_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The recurring weekly split + any upcoming per-date overrides + today's effective day-type."""
    today = today_ph()
    return {
        "week": gym_svc.get_week(db, user.id),
        "cardio": gym_svc.get_cardio(db, user.id),
        "weekdays": GYM_WEEKDAYS,
        "day_types": GYM_PLAN_DAY_TYPES,
        "overrides": gym_svc.upcoming_overrides(db, user.id, today),
        "today": {"date": today.isoformat(), "day_type": gym_svc.effective_plan(db, user.id, today)},
    }


@router.post("/plan/week")
def set_plan_week(payload: GymPlanWeekIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Replace the recurring weekly split (Mon..Sun → a plan day-type or Rest) + optional cardio notes."""
    week, cardio = gym_svc.set_week(db, user.id, payload.week, payload.cardio)
    return {"week": week, "cardio": cardio}


@router.post("/plan/day")
def set_plan_day(payload: GymPlanDayIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Override the plan for a single date (move a split onto it, mark it Rest, and/or note a run)."""
    if payload.day_type not in GYM_PLAN_DAY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid day type")
    gym_svc.set_override(db, user.id, payload.date, payload.day_type, payload.cardio)
    return {"date": payload.date.isoformat(), "day_type": payload.day_type, "cardio": payload.cardio or None}


@router.delete("/plan/day/{on}", status_code=204)
def clear_plan_day(on: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Drop a date's override — it reverts to whatever the weekly split says."""
    gym_svc.clear_override(db, user.id, on)


@router.get("/calendar")
def calendar(
    month: str | None = Query(None, description="YYYY-MM; defaults to the current month"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-day view for the calendar grid: the planned split for every date in the month, merged
    with any session the user actually logged that day."""
    today = today_ph()
    try:
        year, mon = (int(x) for x in (month or today.strftime("%Y-%m")).split("-"))
        first = date(year, mon, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Bad month (want YYYY-MM)")
    last = date(year, mon, _calendar.monthrange(year, mon)[1])
    plan = gym_svc.plan_for_range(db, user.id, first, last)
    logs = {
        g.date: g
        for g in db.execute(
            select(GymLog).where(
                GymLog.user_id == user.id, GymLog.date >= first, GymLog.date <= last
            )
        ).scalars()
    }
    days = []
    d = first
    while d <= last:
        g = logs.get(d)
        days.append({
            "date": d.isoformat(),
            "weekday": GYM_WEEKDAYS[d.weekday()],
            "planned": plan[d]["day_type"],
            "cardio": plan[d]["cardio"],
            "is_today": d == today,
            "log": {
                "id": g.id,
                "day_type": g.day_type,
                "status": g.status,
                "duration_minutes": g.duration_minutes,
                "exercise_count": len(g.exercises),
            } if g else None,
        })
        d += timedelta(days=1)
    return {"month": first.strftime("%Y-%m"), "days": days}


@router.get("/summary")
def summary(
    team_id: int | None = Query(None),
    admin: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
    db: Session = Depends(get_db),
):
    """Week-to-date compliance per user (Completed / Incomplete / Missing)."""
    start = today_ph() - timedelta(days=today_ph().weekday())  # Monday
    users_q = select(User).where(User.is_active.is_(True))
    if team_id:
        users_q = users_q.where(User.team_id == team_id)
    if admin.role == ROLE_TEAM_LEAD:
        users_q = users_q.where(User.team_id == admin.team_id)
    users = db.execute(users_q).scalars().all()
    out = []
    for u in users:
        logs = db.execute(
            select(GymLog).where(GymLog.user_id == u.id, GymLog.date >= start)
        ).scalars().all()
        completed = sum(1 for g in logs if g.status == "Completed")
        incomplete = sum(1 for g in logs if g.status == "Incomplete")
        out.append(
            {
                "user_id": u.id,
                "name": u.name,
                "team_id": u.team_id,
                "sessions": len(logs),
                "completed": completed,
                "incomplete": incomplete,
                "logs": [gym_log_dict(g, db) for g in logs],
            }
        )
    return out


@router.patch("/{log_id}")
def admin_edit_log(
    log_id: int,
    payload: GymAdminEditIn,
    admin: User = Depends(require_roles(ROLE_SUPER_ADMIN)),
    db: Session = Depends(get_db),
):
    """Super Admin correction of any user's session (day type / status / notes)."""
    log = db.get(GymLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Session not found")
    old = {"day_type": log.day_type, "status": log.status, "notes": log.notes}
    if payload.day_type:
        if payload.day_type not in GYM_DAY_TYPES:
            raise HTTPException(status_code=400, detail="Invalid day type")
        log.day_type = payload.day_type
    if payload.status:
        log.status = payload.status
    if payload.notes is not None:
        log.notes = payload.notes
    audit.record(db, actor_id=admin.id, table_name="gym_logs", record_id=log.id, action="edit",
                 old=old, new={"day_type": log.day_type, "status": log.status, "notes": log.notes},
                 commit=False)
    db.commit()
    return gym_log_dict(log, db, with_exercises=True)


@router.delete("/{log_id}", status_code=204)
def delete_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a gym session — your own, or (Super Admin) anyone's."""
    log = db.get(GymLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Session not found")
    if log.user_id != user.id and user.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not your session")
    audit.record(db, actor_id=user.id, table_name="gym_logs", record_id=log.id, action="delete",
                 old={"user_id": log.user_id, "date": str(log.date), "day_type": log.day_type}, commit=False)
    db.delete(log)
    db.commit()


@router.get("/{log_id}")
def get_log(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = db.get(GymLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Session not found")
    # Own session, or any if admin/lead.
    if log.user_id != user.id and user.role not in {"admin", "super_admin", "team_lead"}:
        raise HTTPException(status_code=403, detail="Not your session")
    return {"log": gym_log_dict(log, db, with_exercises=True), "summary": gym_svc.session_summary(log)}
