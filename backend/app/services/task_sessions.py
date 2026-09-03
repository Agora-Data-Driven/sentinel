"""Per-task WORK SESSIONS — the first time Sentinel records time spent on a task (2026-09-02).

Until this module the only time Sentinel knew was attendance (clock in → clock out) and the Mastery
Engine's learning minutes. Nothing said how long a card took, so the Monitor's capacity column had to
stay a relative card count (`task_analytics`, "a task on this board has no size"). Sessions are what
finally give a card a size that is MEASURED rather than guessed.

The rules, each of which is a decision:

* **Start Work opens a session; anything that ends the work closes it.** Pause, Submit for review,
  Park, starting a different card, and clocking out all close the open session. Nobody reconstructs
  a timesheet at the end of the day — the honest default is that the timer was running.
* **One open session per person.** Starting a second card pauses the first. A person cannot be
  working two things at once, and two open timers would double-count the same minutes.
* **A runaway session is CAPPED, not trusted.** A timer left running overnight would otherwise
  record 16h on one card. Past `settings.session_cap_minutes` (4h) the row is clamped to the cap
  and marked `auto_cap`, so the person sees a flagged block they can trim — never a silently
  inflated day, never a silently lost one.
* **Sessions are never edited in place.** A correction is a new `manual` row with a note, so the
  audit stays honest — the same rule the engine's minutes follow (delete/trim, never extend).
* **Session time is INTERNAL.** It never crosses to the client (`task_bridge.SAFE` is unchanged) and
  never reaches Atrium's staff mirror either — how long we took is not what the client bought.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Task, TaskSession, User
from ..utils.time import utcnow

PH_OFFSET = timedelta(hours=8)


def _cap() -> int:
    return max(30, int(getattr(settings, "session_cap_minutes", 240) or 240))


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """The UTC instants a PH calendar day spans — sessions are bucketed by the day they STARTED."""
    start = datetime(day.year, day.month, day.day) - PH_OFFSET
    return start, start + timedelta(days=1)


def active_for(db: Session, user_id: int) -> TaskSession | None:
    """The one session this person has running, or None."""
    return db.execute(
        select(TaskSession)
        .where(TaskSession.user_id == user_id, TaskSession.ended_at.is_(None))
        .order_by(TaskSession.started_at.desc())
    ).scalars().first()


def active_by_user(db: Session, user_ids: list[int]) -> dict[int, TaskSession]:
    """Every running session across `user_ids`, keyed by person — ONE query for a whole table.

    "One open session per person" is the module's rule, so the dict holds at most one row each; if
    a stray duplicate ever exists the most recently started one wins, matching `active_for`."""
    if not user_ids:
        return {}
    rows = db.execute(
        select(TaskSession)
        .where(TaskSession.user_id.in_(user_ids), TaskSession.ended_at.is_(None))
        .order_by(TaskSession.started_at)
    ).scalars().all()
    return {s.user_id: s for s in rows}


def _close(s: TaskSession, source: str, now: datetime, note: str | None = None) -> None:
    cap = _cap()
    elapsed = (now - s.started_at).total_seconds() / 60
    if elapsed > cap:
        # Clamp and SAY so — the person trims it, the day does not quietly grow by a forgotten timer.
        s.ended_at = s.started_at + timedelta(minutes=cap)
        s.source = "auto_cap"
        s.note = ((note + " · ") if note else "") + f"Ran past {cap} min and was capped."
    else:
        s.ended_at = now
        s.source = source
        if note:
            s.note = note


def close_open(db: Session, user_id: int, source: str = "start_work",
               note: str | None = None) -> list[TaskSession]:
    """End every open session this person has (normally exactly one). Returns the rows closed."""
    now = utcnow()
    rows = db.execute(
        select(TaskSession).where(TaskSession.user_id == user_id, TaskSession.ended_at.is_(None))
    ).scalars().all()
    for s in rows:
        _close(s, source, now, note)
    return rows


def start(db: Session, task: Task, user: User) -> tuple[TaskSession, list[TaskSession]]:
    """Open a session on `task` for `user`, closing whatever they had running first.

    Returns (new_session, closed). Starting the card you are already on is a no-op that returns the
    running session — a double-click must not split one block of work into two rows.
    """
    current = active_for(db, user.id)
    if current is not None and current.task_id == task.id:
        return current, []
    closed = close_open(db, user.id, source="start_work") if current is not None else []
    s = TaskSession(task_id=task.id, user_id=user.id, started_at=utcnow(), source="start_work")
    db.add(s)
    db.flush()
    return s, closed


def close_for_task(db: Session, task: Task, user: User, source: str = "start_work") -> TaskSession | None:
    """End the running session if it is on THIS task (Pause / Submit / Park press this)."""
    current = active_for(db, user.id)
    if current is None or current.task_id != task.id:
        return None
    _close(current, source, utcnow())
    return current


def sessions_for_task(db: Session, task_id: int) -> list[TaskSession]:
    return db.execute(
        select(TaskSession).where(TaskSession.task_id == task_id).order_by(TaskSession.started_at)
    ).scalars().all()


def minutes_by_task(db: Session, task_ids: list[int]) -> dict[int, int]:
    """Total recorded minutes per task (a running session counts up to now)."""
    if not task_ids:
        return {}
    rows = db.execute(select(TaskSession).where(TaskSession.task_id.in_(task_ids))).scalars().all()
    out: dict[int, int] = {}
    for s in rows:
        out[s.task_id] = out.get(s.task_id, 0) + s.minutes
    return out


def sessions_between(db: Session, user_ids: list[int], frm: datetime, to: datetime) -> list[TaskSession]:
    if not user_ids:
        return []
    return db.execute(
        select(TaskSession).where(
            TaskSession.user_id.in_(user_ids),
            TaskSession.started_at >= frm, TaskSession.started_at < to,
        ).order_by(TaskSession.started_at)
    ).scalars().all()


def minutes_by_user(db: Session, user_ids: list[int], frm: datetime, to: datetime) -> dict[int, int]:
    out: dict[int, int] = {}
    for s in sessions_between(db, user_ids, frm, to):
        out[s.user_id] = out.get(s.user_id, 0) + s.minutes
    return out


def today_for_user(db: Session, user_id: int, day: date) -> list[TaskSession]:
    frm, to = day_bounds_utc(day)
    return sessions_between(db, [user_id], frm, to)


def session_dict(s: TaskSession, task: Task | None = None) -> dict:
    return {
        "id": s.id,
        "task_id": s.task_id,
        "task_title": task.title if task is not None else None,
        "client_id": task.client_id if task is not None else None,
        "user_id": s.user_id,
        "started_at": s.started_at.isoformat() + "Z",
        "ended_at": (s.ended_at.isoformat() + "Z") if s.ended_at else None,
        "minutes": s.minutes,
        "running": s.ended_at is None,
        "source": s.source,
        "note": s.note,
    }
