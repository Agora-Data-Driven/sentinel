"""TODAY — the specialist's landing page payload (2026-09-02).

Three kinds of time, one honest read:

    attendance   clock in → now (or clock out), minus punched breaks      `attendance_events`
    task time    Start Work sessions, split client / internal              `task_sessions`
    learning     the Mastery Engine's active minutes (+ hand-logged)       `time_spent`

`unallocated` is attendance minus the other two — clocked in with no session running. It is not a
fault and the page says so; it is what nobody pressed Start on. Learning is `None`, never 0, when the
engine bridge fails (the same rule `time_spent` follows: "—" is unknown, "0m" is zero), and in that
case unallocated is computed without it and flagged.

Training today comes from the engine's enrollment rollup: the person's enrolled programmes and how
far along each one is. Sentinel links into the engine; it never stores curricula.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ACTION_BREAK_END, ACTION_BREAK_START, ACTION_CLOCK_IN, ACTION_CLOCK_OUT
from ..models import Task, User
from ..utils.time import minutes_between, today_ph, utcnow
from . import attendance as att
from . import engine_bridge, task_sessions, time_spent


def attendance_minutes(db: Session, user: User, day: date) -> dict:
    """Minutes clocked in so far today (breaks removed), plus the punches themselves."""
    events = att._events_for(db, user.id, day)
    clock_in = next((e.time for e in events if e.action == ACTION_CLOCK_IN), None)
    clock_out = next((e.time for e in reversed(events) if e.action == ACTION_CLOCK_OUT), None)
    if not clock_in:
        return {"clock_in": None, "clock_out": None, "minutes": None, "state": att.current_state(events)}
    end = clock_out or utcnow()
    breaks = 0
    open_break = None
    for e in events:
        if e.action == ACTION_BREAK_START:
            open_break = e.time
        elif e.action == ACTION_BREAK_END and open_break:
            breaks += minutes_between(open_break, e.time)
            open_break = None
    if open_break and not clock_out:
        breaks += minutes_between(open_break, end)
    return {
        "clock_in": clock_in.isoformat() + "Z",
        "clock_out": (clock_out.isoformat() + "Z") if clock_out else None,
        "minutes": max(0, minutes_between(clock_in, end) - breaks),
        "state": att.current_state(events),
    }


def time_today(db: Session, user: User, day: date | None = None) -> dict:
    day = day or today_ph()
    attendance = attendance_minutes(db, user, day)
    sessions = task_sessions.today_for_user(db, user.id, day)
    task_ids = {s.task_id for s in sessions}
    tasks = {t.id: t for t in db.execute(select(Task).where(Task.id.in_(task_ids or [-1]))).scalars()}
    client_min = internal_min = 0
    for s in sessions:
        t = tasks.get(s.task_id)
        if t is not None and t.client_id:
            client_min += s.minutes
        else:
            internal_min += s.minutes
    learning = time_spent.summary(db, user, "today")
    learning_min = learning.get("total")           # None = the engine could not be read
    active = task_sessions.active_for(db, user.id)
    att_min = attendance["minutes"]
    unallocated = None
    if att_min is not None:
        unallocated = max(0, att_min - client_min - internal_min - int(learning_min or 0))
    return {
        "date": day.isoformat(),
        "attendance": attendance,
        "client_minutes": client_min,
        "internal_minutes": internal_min,
        "learning_minutes": learning_min,
        "learning_error": learning.get("engine_error") or "",
        "unallocated_minutes": unallocated,
        "active_minutes": client_min + internal_min + int(learning_min or 0),
        "sessions": [task_sessions.session_dict(s, tasks.get(s.task_id)) for s in sessions],
        "active_session": task_sessions.session_dict(active, tasks.get(active.task_id) if active else None)
        if active else None,
    }


def training(user: User) -> dict:
    """The person's enrolled programmes from the engine — what "Training today" lists."""
    if not engine_bridge.enabled():
        return {"programs": [], "error": "the Mastery Engine bridge isn't configured"}
    status, data, err = engine_bridge.call(
        "enrollment-progress", "/api/internal/enrollment-progress",
        params={"email": (user.email or "").strip().lower()},
    )
    if status != 200 or not isinstance(data, dict):
        return {"programs": [], "error": err or f"the Mastery Engine answered {status}"}
    programs = []
    for p in data.get("programs") or []:
        if not isinstance(p, dict):
            continue
        pct = p.get("pct")
        programs.append({
            "id": p.get("id"),
            "name": p.get("name") or p.get("id"),
            "category": p.get("category"),
            "pct": int(pct) if isinstance(pct, (int, float)) else None,
            "topics_total": p.get("topicsTotal"),
            "topics_practiced": p.get("topicsPracticed"),
        })
    return {"programs": programs, "error": ""}


def payload(db: Session, user: User) -> dict:
    return {"time": time_today(db, user), "training": training(user)}
