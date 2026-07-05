"""Attendance engine: shift resolution, punch validation, late detection, summary recompute.

All wall-clock reasoning happens in Asia/Manila; instants are stored UTC. The daily summary is a
pure projection of the day's raw ``attendance_events`` — recompute it after every punch or edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    ACTION_BREAK_END,
    ACTION_BREAK_START,
    ACTION_CLOCK_IN,
    ACTION_CLOCK_OUT,
    STATUS_ABSENT,
    STATUS_HALF_DAY,
    STATUS_LATE,
    STATUS_MISSING_CLOCKOUT,
    STATUS_ON_TIME,
)
from ..models import AttendanceEvent, DailyAttendanceSummary, Team, User
from ..utils.time import PH_TZ, minutes_between, parse_hhmm, to_ph
from . import settings as settings_svc


@dataclass
class Shift:
    start: str  # "HH:MM"
    end: str
    grace_min: int
    break_min: int


def effective_shift(db: Session, user: User) -> Shift:
    """Resolve a user's shift: per-employee override → team → system defaults."""
    smap = settings_svc.get_map(db)
    grace = int(smap.get("late_grace", "15"))
    start = smap.get("work_start", "08:00")
    end = smap.get("work_end", "17:00")
    break_min = int(smap.get("break_duration", "60"))

    if user.team_id:
        team = db.get(Team, user.team_id)
        if team:
            start, end, break_min = team.shift_start, team.shift_end, team.break_duration_min
    if user.shift_start:
        start = user.shift_start
    if user.shift_end:
        end = user.shift_end
    return Shift(start=start, end=end, grace_min=grace, break_min=break_min)


def _events_for(db: Session, user_id: int, day: date) -> list[AttendanceEvent]:
    rows = db.execute(
        select(AttendanceEvent)
        .where(AttendanceEvent.user_id == user_id, AttendanceEvent.date == day)
        .order_by(AttendanceEvent.time.asc())
    ).scalars().all()
    return list(rows)


def current_state(events: list[AttendanceEvent]) -> str:
    """Derive kiosk state from the day's events: 'none' | 'in' | 'on_break' | 'out'."""
    state = "none"
    for e in events:
        if e.action == ACTION_CLOCK_IN:
            state = "in"
        elif e.action == ACTION_BREAK_START and state == "in":
            state = "on_break"
        elif e.action == ACTION_BREAK_END and state == "on_break":
            state = "in"
        elif e.action == ACTION_CLOCK_OUT:
            state = "out"
    return state


def valid_actions(events: list[AttendanceEvent]) -> list[str]:
    """Which punches are allowed right now (drives the kiosk's four big buttons)."""
    state = current_state(events)
    if state == "none":
        return [ACTION_CLOCK_IN]
    if state in ("in", "on_break"):  # breaks aren't tracked; only clock-out is offered
        return [ACTION_CLOCK_OUT]
    return []  # already clocked out


def validate_action(events: list[AttendanceEvent], action: str) -> str | None:
    """Return an error message if ``action`` is illegal given today's punches, else None."""
    state = current_state(events)
    if action == ACTION_CLOCK_IN:
        if state != "none":
            return "Already clocked in today"
    elif action == ACTION_CLOCK_OUT:
        if state == "none":
            return "Cannot clock out without clocking in"
        if state == "out":
            return "Already clocked out today"
    elif action == ACTION_BREAK_START:
        if state == "none":
            return "Cannot start a break before clocking in"
        if state == "on_break":
            return "Break already started"
        if state == "out":
            return "Cannot start a break after clocking out"
    elif action == ACTION_BREAK_END:
        if state != "on_break":
            return "No break in progress"
    else:
        return "Unknown action"
    return None


def compute_late(clock_in_utc: datetime, shift: Shift) -> tuple[str, int]:
    """Given a clock-in instant, decide OnTime/Late and the minutes late (PH time + grace)."""
    local = to_ph(clock_in_utc)
    st = parse_hhmm(shift.start)
    threshold = local.replace(
        hour=st.hour, minute=st.minute, second=0, microsecond=0
    ) + timedelta(minutes=shift.grace_min)
    if local > threshold:
        return STATUS_LATE, minutes_between(threshold, local)
    return STATUS_ON_TIME, 0


def recompute_summary(db: Session, user: User, day: date, commit: bool = True) -> DailyAttendanceSummary:
    """Rebuild (or create) the daily summary row from the day's events."""
    events = _events_for(db, user.id, day)
    shift = effective_shift(db, user)

    summary = db.execute(
        select(DailyAttendanceSummary).where(
            DailyAttendanceSummary.user_id == user.id, DailyAttendanceSummary.date == day
        )
    ).scalar_one_or_none()
    if summary is None:
        summary = DailyAttendanceSummary(user_id=user.id, date=day)
        db.add(summary)

    clock_in = next((e.time for e in events if e.action == ACTION_CLOCK_IN), None)
    clock_out = next((e.time for e in reversed(events) if e.action == ACTION_CLOCK_OUT), None)
    break_start = next((e.time for e in events if e.action == ACTION_BREAK_START), None)
    break_end = next((e.time for e in events if e.action == ACTION_BREAK_END), None)
    handover = next((e.handover_note for e in reversed(events) if e.action == ACTION_CLOCK_OUT), None)

    # Sum every completed break pair in the day.
    break_minutes = 0
    open_break: datetime | None = None
    for e in events:
        if e.action == ACTION_BREAK_START:
            open_break = e.time
        elif e.action == ACTION_BREAK_END and open_break:
            break_minutes += minutes_between(open_break, e.time)
            open_break = None

    summary.clock_in = clock_in
    summary.clock_out = clock_out
    summary.break_start = break_start
    summary.break_end = break_end
    # Breaks aren't punched anymore — deduct the shift's fixed unpaid lunch from worked hours.
    lunch = shift.break_min if (clock_in and clock_out) else 0
    summary.break_duration_min = lunch
    summary.handover_note = handover

    # Work hours = clock-in -> clock-out minus the fixed lunch. Overtime is NOT tracked in Sentinel.
    worked_minutes = max(0, minutes_between(clock_in, clock_out) - lunch) if (clock_in and clock_out) else 0
    summary.total_work_hours = round(worked_minutes / 60.0, 2)
    summary.overtime_minutes = 0

    shift_minutes = _shift_minutes(shift)  # used only for the half-day status check below

    # Status.
    if not clock_in:
        summary.status = STATUS_ABSENT
    elif not clock_out:
        summary.status = STATUS_MISSING_CLOCKOUT
    elif worked_minutes < shift_minutes / 2:
        summary.status = STATUS_HALF_DAY
    else:
        late_status, _ = compute_late(clock_in, shift)
        summary.status = late_status

    if commit:
        db.commit()
    return summary


def _shift_minutes(shift: Shift) -> int:
    st, en = parse_hhmm(shift.start), parse_hhmm(shift.end)
    total = (en.hour * 60 + en.minute) - (st.hour * 60 + st.minute)
    return max(0, total - shift.break_min)
