"""Attendance engine: late/grace math across the UTC↔Manila boundary + the punch state machine.

Punches are stored as naive UTC; all late/grace reasoning happens in Asia/Manila (UTC+8). The
tricky cases are around the grace edge and the date boundary (an 08:00 Manila shift start is
00:00 UTC the same day), so those are covered explicitly.
"""
from __future__ import annotations

from datetime import datetime

from app import constants as C
from app.services.attendance import (
    Shift,
    current_state,
    valid_actions,
    validate_action,
    compute_late,
)
from app.models import AttendanceEvent

SHIFT = Shift(start="08:00", end="17:00", grace_min=15, break_min=60)


def _utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi)  # naive UTC, as stored


# --- compute_late: 08:00 Manila start == 00:00 UTC, grace 15 min -----------
def test_on_time_exactly_at_shift_start():
    # 00:00 UTC == 08:00 Manila == shift start.
    status, mins = compute_late(_utc(2026, 7, 17, 0, 0), SHIFT)
    assert status == C.STATUS_ON_TIME and mins == 0


def test_within_grace_is_on_time():
    # 08:14 Manila (within 15-min grace) == 00:14 UTC.
    status, mins = compute_late(_utc(2026, 7, 17, 0, 14), SHIFT)
    assert status == C.STATUS_ON_TIME and mins == 0


def test_exactly_at_grace_edge_is_on_time():
    # 08:15 Manila is the last on-time minute (late only when strictly past the threshold).
    status, mins = compute_late(_utc(2026, 7, 17, 0, 15), SHIFT)
    assert status == C.STATUS_ON_TIME and mins == 0


def test_one_minute_past_grace_is_late():
    # 08:16 Manila == 00:16 UTC -> 1 minute past the 08:15 threshold.
    status, mins = compute_late(_utc(2026, 7, 17, 0, 16), SHIFT)
    assert status == C.STATUS_LATE and mins == 1


def test_late_minutes_counted_from_grace_threshold():
    # 09:00 Manila == 01:00 UTC -> 45 min past the 08:15 threshold.
    status, mins = compute_late(_utc(2026, 7, 17, 1, 0), SHIFT)
    assert status == C.STATUS_LATE and mins == 45


def test_pre_midnight_utc_maps_to_next_day_manila():
    # 23:30 UTC on Jul 16 == 07:30 Manila on Jul 17 -> early, on time.
    status, mins = compute_late(_utc(2026, 7, 16, 23, 30), SHIFT)
    assert status == C.STATUS_ON_TIME and mins == 0


def test_zero_grace_shift_is_late_one_minute_after_start():
    strict = Shift(start="09:00", end="18:00", grace_min=0, break_min=60)
    status, mins = compute_late(_utc(2026, 7, 17, 1, 1), strict)  # 09:01 Manila
    assert status == C.STATUS_LATE and mins == 1


# --- punch state machine ---------------------------------------------------
def _ev(action):
    return AttendanceEvent(action=action)


def test_state_progression():
    assert current_state([]) == "none"
    assert current_state([_ev(C.ACTION_CLOCK_IN)]) == "in"
    assert current_state([_ev(C.ACTION_CLOCK_IN), _ev(C.ACTION_BREAK_START)]) == "on_break"
    assert current_state([_ev(C.ACTION_CLOCK_IN), _ev(C.ACTION_BREAK_START), _ev(C.ACTION_BREAK_END)]) == "in"
    assert current_state([_ev(C.ACTION_CLOCK_IN), _ev(C.ACTION_CLOCK_OUT)]) == "out"


def test_valid_actions_by_state():
    assert valid_actions([]) == [C.ACTION_CLOCK_IN]
    assert valid_actions([_ev(C.ACTION_CLOCK_IN)]) == [C.ACTION_CLOCK_OUT]
    assert valid_actions([_ev(C.ACTION_CLOCK_IN), _ev(C.ACTION_CLOCK_OUT)]) == []


def test_cannot_clock_in_twice():
    assert validate_action([_ev(C.ACTION_CLOCK_IN)], C.ACTION_CLOCK_IN) is not None


def test_cannot_clock_out_without_clocking_in():
    assert validate_action([], C.ACTION_CLOCK_OUT) is not None


def test_cannot_clock_out_twice():
    events = [_ev(C.ACTION_CLOCK_IN), _ev(C.ACTION_CLOCK_OUT)]
    assert validate_action(events, C.ACTION_CLOCK_OUT) is not None


def test_legal_clock_in_then_out_returns_no_error():
    assert validate_action([], C.ACTION_CLOCK_IN) is None
    assert validate_action([_ev(C.ACTION_CLOCK_IN)], C.ACTION_CLOCK_OUT) is None
