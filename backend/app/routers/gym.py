"""Gym Tracker: session start/end, Hevy-style exercise logging, library, compliance."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import GYM_DAY_TYPES, ROLE_SUPER_ADMIN, ROLE_TEAM_LEAD
from ..database import get_db
from ..models import ExerciseLibrary, GymExercise, GymLog, User
from ..schemas import GymAdminEditIn, GymEndIn, GymExerciseIn, GymStartIn
from ..security import get_current_user, require_min_role, require_roles
from ..serializers import gym_log_dict
from ..services import audit
from ..services import gym as gym_svc
from ..services import settings as settings_svc
from ..utils.time import minutes_between, today_ph, utcnow

router = APIRouter(prefix="/api/gym", tags=["gym"])


def _required_hours(db: Session) -> float:
    return float(settings_svc.get(db, "gym_required_hours") or "1")


@router.post("/start")
def start(payload: GymStartIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.day_type not in GYM_DAY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid day type")
    day = today_ph()
    existing = db.execute(
        select(GymLog).where(GymLog.user_id == user.id, GymLog.date == day)
    ).scalar_one_or_none()
    if existing and existing.end_time:
        raise HTTPException(status_code=409, detail="Today's session is already finished")
    log = existing or GymLog(user_id=user.id, date=day)
    log.day_type = payload.day_type
    log.start_time = log.start_time or utcnow()
    log.status = "Incomplete"
    if not existing:
        db.add(log)
    db.commit()
    return gym_log_dict(log, db, with_exercises=True)


@router.post("/{log_id}/end")
def end(log_id: int, payload: GymEndIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    log = db.get(GymLog, log_id)
    if not log or log.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    log.end_time = utcnow()
    if payload.notes is not None:
        log.notes = payload.notes
    if log.start_time:
        log.duration_minutes = max(0, minutes_between(log.start_time, log.end_time))
    log.status = gym_svc.compute_status(log.duration_minutes, len(log.exercises), _required_hours(db))
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
    log.status = gym_svc.compute_status(log.duration_minutes, len(payload), _required_hours(db))
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
def admin_delete_log(
    log_id: int,
    admin: User = Depends(require_roles(ROLE_SUPER_ADMIN)),
    db: Session = Depends(get_db),
):
    """Super Admin: delete any user's gym session."""
    log = db.get(GymLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Session not found")
    audit.record(db, actor_id=admin.id, table_name="gym_logs", record_id=log.id, action="delete",
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
