"""Gym logic: compliance status, the Hevy 'PREVIOUS' lookup, session summary math, the weekly
plan (recurring split + per-date overrides) that drives the calendar, and saved routines
(named workout templates you drop onto a day in one tap)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    GYM_COMPLETED,
    GYM_DAY_TYPES,
    GYM_DEFAULT_WEEK,
    GYM_INCOMPLETE,
    GYM_MISSING,
    GYM_PLAN_DAY_TYPES,
    GYM_WEEKDAYS,
)
from ..models import GymExercise, GymLog, GymPlanOverride, GymRoutine, GymSchedule


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


# --- Routines (saved workout templates) ------------------------------------
#
# The maintenance-training problem: when every Monday Push is the same eleven exercises at the same
# weights, re-entering them by hand is the whole cost of logging. A routine holds that list once;
# `apply_routine` stamps it onto any day's session.
#
# Names are free text on purpose ("Push A" / "Push B", not "Monday Push") — the same split gets run
# more than one way, and the day it lands on is the schedule's business, not the routine's.

_MAX_ROUTINE_EXERCISES = 40
_MAX_ROUTINE_SETS = 20


def _clean_str(v, limit: int) -> str | None:
    return v.strip()[:limit] if isinstance(v, str) and v.strip() else None


def normalize_routine_exercises(items) -> list[dict]:
    """Coerce an inbound exercise list into the stored template shape, dropping anything unusable.

    A template set carries only what you'd pre-fill — weight, reps, set type. It deliberately has
    no ``done`` flag: ticking sets off is what you do while training, and a routine that arrived
    pre-ticked would silently mark work you haven't done yet.
    """
    out: list[dict] = []
    for raw in (items or [])[:_MAX_ROUTINE_EXERCISES]:
        if not isinstance(raw, dict):
            continue
        name = _clean_str(raw.get("exercise_name"), 120)
        if not name:
            continue
        sets = []
        for s in (raw.get("sets") or [])[:_MAX_ROUTINE_SETS]:
            if not isinstance(s, dict):
                continue
            sets.append({
                "kg": max(0.0, float(s.get("kg") or 0)),
                "reps": max(0, int(s.get("reps") or 0)),
                "type": _clean_str(s.get("type"), 16) or "Normal",
            })
        out.append({
            "exercise_name": name,
            "muscle_group": _clean_str(raw.get("muscle_group"), 60),
            # An exercise with no sets is still a valid line ("do this, weight TBD") — one blank set
            # keeps the editor from rendering an empty table.
            "sets": sets or [{"kg": 0, "reps": 0, "type": "Normal"}],
            "notes": _clean_str(raw.get("notes"), 500),
        })
    return out


def normalize_weekdays(v) -> list[str]:
    """Keep only real weekday keys, in Mon..Sun order, no duplicates."""
    given = {x for x in (v or []) if isinstance(x, str)}
    return [wd for wd in GYM_WEEKDAYS if wd in given]


def exercises_from_log(log: GymLog) -> list[dict]:
    """Turn a logged session into template rows — the zero-typing way to create a routine.

    Warm-up sets ride along as they were logged; the weights are whatever you actually lifted, which
    for maintenance training is exactly the number you want back next week.
    """
    items = []
    for ex in log.exercises:
        try:
            detail = json.loads(ex.sets_json or "[]")
        except (ValueError, TypeError):
            detail = []
        sets = [{"kg": s.get("kg", 0), "reps": s.get("reps", 0), "type": s.get("type", "Normal")}
                for s in detail if isinstance(s, dict)]
        if not sets:  # a pre-Hevy row that only has the summary columns
            sets = [{"kg": ex.weight_value or 0, "reps": ex.reps or 0, "type": ex.set_type or "Normal"}
                    for _ in range(max(1, ex.sets or 1))]
        items.append({
            "exercise_name": ex.exercise_name,
            "muscle_group": ex.muscle_group,
            "sets": sets,
            "notes": ex.notes,
        })
    return normalize_routine_exercises(items)


def list_routines(db: Session, user_id: int) -> list[GymRoutine]:
    return list(db.execute(
        select(GymRoutine)
        .where(GymRoutine.user_id == user_id)
        .order_by(GymRoutine.sort_order, GymRoutine.day_type, GymRoutine.name)
    ).scalars())


def get_routine(db: Session, user_id: int, routine_id: int) -> GymRoutine | None:
    """Fetch one routine, scoped to its owner — routines are private, like every other gym row."""
    r = db.get(GymRoutine, routine_id)
    return r if r and r.user_id == user_id else None


def suggest_routine_name(db: Session, user_id: int, day_type: str) -> str:
    """"Push A", then "Push B"… — the naming users reach for anyway when a split runs two ways."""
    taken = {r.name.strip().lower() for r in list_routines(db, user_id)}
    for suffix in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = f"{day_type} {suffix}"
        if candidate.lower() not in taken:
            return candidate
    return day_type


def set_routine_weekdays(db: Session, user_id: int, routine: GymRoutine, weekdays) -> list[str]:
    """Make `routine` the default for these weekdays, taking them off any other routine.

    A weekday with two defaults has none — "what am I doing today?" must have one answer, so the
    assignment moves rather than duplicating.
    """
    wanted = normalize_weekdays(weekdays)
    for other in list_routines(db, user_id):
        if other.id == routine.id:
            continue
        kept = [wd for wd in _routine_weekdays(other) if wd not in wanted]
        if kept != _routine_weekdays(other):
            other.weekdays_json = json.dumps(kept)
    routine.weekdays_json = json.dumps(wanted)
    return wanted


def _routine_weekdays(r: GymRoutine) -> list[str]:
    try:
        return normalize_weekdays(json.loads(r.weekdays_json or "[]"))
    except (ValueError, TypeError):
        return []


def routine_weekday_map(db: Session, user_id: int) -> dict[str, int]:
    """{"Mon": routine_id} — what the plan and the Today tab pre-load for each weekday."""
    out: dict[str, int] = {}
    for r in list_routines(db, user_id):
        for wd in _routine_weekdays(r):
            out.setdefault(wd, r.id)
    return out


def routine_summary_lines(db: Session, user_id: int) -> list[str]:
    """One compact line per routine for the AI coach's digest — names, splits and weekday defaults.

    Names only, never the exercise lists: the coach needs to know "you have a Push A pinned to
    Monday" to talk about the week; the sets and reps are the app's job, and would cost far more
    context than they're worth.
    """
    lines = []
    for r in list_routines(db, user_id):
        wd = _routine_weekdays(r)
        try:
            n = len(json.loads(r.exercises_json or "[]"))
        except (ValueError, TypeError):
            n = 0
        lines.append(f"{r.name} ({r.day_type}, {n} exercises"
                     f"{', default for ' + '/'.join(wd) if wd else ''})")
    return lines


def apply_routine(db: Session, log: GymLog, routine: GymRoutine, mode: str = "replace") -> None:
    """Stamp a routine's exercises onto a session. ``replace`` wipes what's there; ``append`` adds.

    On a replace the session also adopts the routine's split — loading "Push A" over a whole day
    means the day IS a push day, and leaving the pill saying "Legs" would just be wrong. Append
    leaves the split alone, since that's the "add some extra work" case.
    """
    if mode == "replace":
        for ex in list(log.exercises):
            db.delete(ex)
        db.flush()
        if routine.day_type in GYM_DAY_TYPES:
            log.day_type = routine.day_type
    try:
        items = normalize_routine_exercises(json.loads(routine.exercises_json or "[]"))
    except (ValueError, TypeError):
        items = []
    for item in items:
        sets_detail = [
            # done=False: these are sets to DO, not sets done. The user ticks them off as they train.
            {"set": i + 1, "kg": s["kg"], "reps": s["reps"], "type": s["type"], "done": False, "pr": False}
            for i, s in enumerate(item["sets"])
        ]
        db.add(GymExercise(
            gym_log_id=log.id,
            exercise_name=item["exercise_name"],
            muscle_group=item["muscle_group"],
            weight_value=max((s["kg"] for s in sets_detail), default=0),
            weight_unit="kg",
            sets=len(sets_detail),
            reps=max((s["reps"] for s in sets_detail), default=0),
            set_type="Normal",
            sets_json=json.dumps(sets_detail),
            duration_minutes=0,
            notes=item["notes"],
        ))
    db.flush()


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
