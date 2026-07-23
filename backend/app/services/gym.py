"""Gym logic: compliance status, the Hevy 'PREVIOUS' lookup, session summary math, and the weekly
plan (recurring split + per-date overrides) that drives the calendar."""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    GYM_COMPLETED,
    GYM_DEFAULT_WEEK,
    GYM_INCOMPLETE,
    GYM_MISSING,
    GYM_PLAN_DAY_TYPES,
    GYM_WEEKDAYS,
)
from ..models import GymExercise, GymLog, GymPlanOverride, GymSchedule


def compute_status(duration_minutes: int, exercise_count: int, required_hours: float) -> str:
    if exercise_count == 0 and duration_minutes == 0:
        return GYM_MISSING
    if duration_minutes >= required_hours * 60 and exercise_count > 0:
        return GYM_COMPLETED
    return GYM_INCOMPLETE


# --- Weekly plan (recurring split + per-date overrides) --------------------

def get_week(db: Session, user_id: int) -> dict[str, str]:
    """The user's recurring weekly split, falling back to the sensible default PPL rotation.
    Always returns a complete, validated Mon..Sun map."""
    row = db.execute(
        select(GymSchedule).where(GymSchedule.user_id == user_id)
    ).scalar_one_or_none()
    stored = {}
    if row:
        try:
            stored = json.loads(row.week_json or "{}")
        except (ValueError, TypeError):
            stored = {}
    return normalize_week(stored)


def normalize_week(week: dict) -> dict[str, str]:
    """Coerce a (possibly partial/dirty) week map into a full Mon..Sun map of valid day-types."""
    out: dict[str, str] = {}
    for wd in GYM_WEEKDAYS:
        val = (week or {}).get(wd)
        out[wd] = val if val in GYM_PLAN_DAY_TYPES else GYM_DEFAULT_WEEK[wd]
    return out


def _clean_cardio(v) -> str | None:
    """A cardio note is free text (e.g. '5k run'); keep it short, drop blanks."""
    if isinstance(v, str) and v.strip():
        return v.strip()[:120]
    return None


def normalize_cardio(cardio: dict) -> dict[str, str]:
    """Sparse Mon..Sun map of cardio notes — only weekdays that actually have one."""
    out: dict[str, str] = {}
    for wd in GYM_WEEKDAYS:
        c = _clean_cardio((cardio or {}).get(wd))
        if c:
            out[wd] = c
    return out


def get_cardio(db: Session, user_id: int) -> dict[str, str]:
    """The user's per-weekday cardio notes (sparse — absent weekdays have no run)."""
    row = db.execute(
        select(GymSchedule).where(GymSchedule.user_id == user_id)
    ).scalar_one_or_none()
    stored = {}
    if row and row.cardio_json:
        try:
            stored = json.loads(row.cardio_json)
        except (ValueError, TypeError):
            stored = {}
    return normalize_cardio(stored)


def effective_plan(db: Session, user_id: int, on: date) -> str:
    """The planned day-type for one date: an override if present, else the weekly template."""
    ov = db.execute(
        select(GymPlanOverride).where(
            GymPlanOverride.user_id == user_id, GymPlanOverride.date == on
        )
    ).scalar_one_or_none()
    if ov:
        return ov.day_type
    return get_week(db, user_id)[GYM_WEEKDAYS[on.weekday()]]


def plan_for_range(db: Session, user_id: int, start: date, end: date) -> dict[date, dict]:
    """Effective {day_type, cardio} for every date in [start, end] (overrides beat the template)."""
    week = get_week(db, user_id)
    cardio = get_cardio(db, user_id)
    rows = db.execute(
        select(GymPlanOverride).where(
            GymPlanOverride.user_id == user_id,
            GymPlanOverride.date >= start,
            GymPlanOverride.date <= end,
        )
    ).scalars().all()
    ov = {r.date: r for r in rows}
    out: dict[date, dict] = {}
    d = start
    while d <= end:
        wd = GYM_WEEKDAYS[d.weekday()]
        if d in ov:
            out[d] = {"day_type": ov[d].day_type, "cardio": ov[d].cardio or None}
        else:
            out[d] = {"day_type": week[wd], "cardio": cardio.get(wd)}
        d += timedelta(days=1)
    return out


def set_week(db: Session, user_id: int, week: dict, cardio: dict | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Replace the weekly split (and, when given, the weekly cardio notes)."""
    normalized = normalize_week(week)
    row = db.execute(
        select(GymSchedule).where(GymSchedule.user_id == user_id)
    ).scalar_one_or_none()
    if not row:
        row = GymSchedule(user_id=user_id)
        db.add(row)
    row.week_json = json.dumps(normalized)
    norm_cardio = normalize_cardio(cardio) if cardio is not None else get_cardio(db, user_id)
    if cardio is not None:
        row.cardio_json = json.dumps(norm_cardio)
    db.commit()
    return normalized, norm_cardio


def set_override(db: Session, user_id: int, on: date, day_type: str, cardio: str | None = None) -> None:
    row = db.execute(
        select(GymPlanOverride).where(
            GymPlanOverride.user_id == user_id, GymPlanOverride.date == on
        )
    ).scalar_one_or_none()
    if not row:
        row = GymPlanOverride(user_id=user_id, date=on)
        db.add(row)
    row.day_type = day_type
    row.cardio = _clean_cardio(cardio)
    db.commit()


def clear_override(db: Session, user_id: int, on: date) -> None:
    row = db.execute(
        select(GymPlanOverride).where(
            GymPlanOverride.user_id == user_id, GymPlanOverride.date == on
        )
    ).scalar_one_or_none()
    if row:
        db.delete(row)
        db.commit()


def upcoming_overrides(db: Session, user_id: int, start: date, days: int = 60) -> list[dict]:
    """Overrides from `start` forward — so a read of the plan shows what's been hand-tweaked."""
    end = start + timedelta(days=days)
    rows = db.execute(
        select(GymPlanOverride)
        .where(
            GymPlanOverride.user_id == user_id,
            GymPlanOverride.date >= start,
            GymPlanOverride.date <= end,
        )
        .order_by(GymPlanOverride.date)
    ).scalars().all()
    return [{"date": r.date.isoformat(), "day_type": r.day_type, "cardio": r.cardio or None} for r in rows]


def previous_for_exercise(db: Session, user_id: int, exercise_name: str, before: date) -> dict | None:
    """Last session's top set for an exercise — the grayed-out Hevy 'PREVIOUS' reference."""
    row = db.execute(
        select(GymExercise)
        .join(GymLog, GymExercise.gym_log_id == GymLog.id)
        .where(
            GymLog.user_id == user_id,
            GymExercise.exercise_name == exercise_name,
            GymLog.date < before,
        )
        .order_by(GymLog.date.desc(), GymExercise.id.desc())
    ).scalars().first()
    if not row:
        return None
    return {
        "date": row.log.date.isoformat() if row.log else None,
        "weight": row.weight_value,
        "unit": row.weight_unit,
        "reps": row.reps,
        "sets": row.sets,
        "display": f"{row.weight_value:g} {row.weight_unit} × {row.reps}" if row.weight_value else f"{row.reps} reps",
    }


def session_summary(log: GymLog) -> dict:
    """Duration, total sets, total volume (kg), PR count, muscle activation breakdown."""
    total_sets = 0
    total_volume = 0.0
    prs = 0
    muscles: dict[str, int] = {}
    for ex in log.exercises:
        try:
            sets = json.loads(ex.sets_json or "[]")
        except (ValueError, TypeError):
            sets = []
        if sets:
            for s in sets:
                total_sets += 1
                total_volume += float(s.get("kg", 0) or 0) * float(s.get("reps", 0) or 0)
                if s.get("pr"):
                    prs += 1
        else:
            total_sets += ex.sets or 0
            total_volume += (ex.weight_value or 0) * (ex.reps or 0) * (ex.sets or 1)
        if ex.muscle_group:
            muscles[ex.muscle_group] = muscles.get(ex.muscle_group, 0) + max(1, ex.sets or 1)
    return {
        "duration_minutes": log.duration_minutes,
        "total_sets": total_sets,
        "total_volume_kg": round(total_volume, 1),
        "new_prs": prs,
        "day_type": log.day_type,
        "muscle_activation": muscles,
    }
