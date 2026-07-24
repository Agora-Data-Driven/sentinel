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


# --- shift templates: variable start/end/length + no phantom lunch (T2) -----
def test_short_shift_template_records_full_hours(db, make_user):
    from datetime import date, datetime
    from app.models import AttendanceEvent, ShiftTemplate
    from app.services.attendance import effective_shift, recompute_summary

    # 6PM–10PM part-time, 0-minute break -> 4 paid hours (the bug recorded 3h via a phantom lunch).
    tpl = ShiftTemplate(name="PT 6-10", start="18:00", end="22:00", break_min=0)
    db.add(tpl)
    db.commit()
    emp = make_user(role=C.ROLE_EMPLOYEE, shift_template_id=tpl.id)

    sh = effective_shift(db, emp)
    assert (sh.start, sh.end, sh.break_min) == ("18:00", "22:00", 0)

    day = date(2026, 7, 20)
    # 18:00 PH == 10:00 UTC ; 22:00 PH == 14:00 UTC
    db.add(AttendanceEvent(user_id=emp.id, date=day, time=datetime(2026, 7, 20, 10, 0), action=C.ACTION_CLOCK_IN))
    db.add(AttendanceEvent(user_id=emp.id, date=day, time=datetime(2026, 7, 20, 14, 0), action=C.ACTION_CLOCK_OUT))
    db.commit()
    s = recompute_summary(db, emp, day, commit=True)
    assert s.total_work_hours == 4.0
    assert s.status == C.STATUS_ON_TIME


def test_afternoon_shift_template_not_marked_late(db, make_user):
    from datetime import datetime
    from app.models import ShiftTemplate
    from app.services.attendance import compute_late, effective_shift

    tpl = ShiftTemplate(name="PM 1-10", start="13:00", end="22:00", break_min=60)
    db.add(tpl)
    db.commit()
    emp = make_user(role=C.ROLE_EMPLOYEE, shift_template_id=tpl.id)
    sh = effective_shift(db, emp)
    # 13:05 PH == 05:05 UTC -> within grace of a 13:00 start, so ON TIME (not ~5h late).
    status, _ = compute_late(datetime(2026, 7, 20, 5, 5), sh)
    assert status == C.STATUS_ON_TIME


def test_employee_template_overrides_team(db, make_user, make_team):
    from app.models import ShiftTemplate
    from app.services.attendance import effective_shift

    team_tpl = ShiftTemplate(name="Team Day", start="08:00", end="17:00", break_min=60)
    emp_tpl = ShiftTemplate(name="Emp PM", start="13:00", end="22:00", break_min=60)
    db.add_all([team_tpl, emp_tpl])
    db.commit()
    team = make_team()
    team.shift_template_id = team_tpl.id
    db.commit()
    emp = make_user(role=C.ROLE_EMPLOYEE, team_id=team.id, shift_template_id=emp_tpl.id)
    assert effective_shift(db, emp).start == "13:00"  # employee template wins over the team's


# --- offline sync is idempotent on replay (client_uid) ----------------------
def test_offline_sync_replay_is_idempotent(db, make_user):
    from datetime import datetime, timezone
    from sqlalchemy import func, select
    from app.models import AttendanceEvent, QRToken
    from app.routers.attendance import offline_sync
    from app.schemas import OfflinePunch, OfflineSyncIn

    emp = make_user(role=C.ROLE_EMPLOYEE)
    db.add(QRToken(user_id=emp.id, token="tok-idem"))
    db.commit()
    punch = OfflinePunch(token="tok-idem", action=C.ACTION_CLOCK_IN,
                         client_time=datetime.now(timezone.utc).isoformat(), uid="uid-abc")
    r1 = offline_sync(OfflineSyncIn(punches=[punch]), db)
    r2 = offline_sync(OfflineSyncIn(punches=[punch]), db)  # re-sync the SAME punch

    n = db.execute(select(func.count(AttendanceEvent.id)).where(
        AttendanceEvent.user_id == emp.id, AttendanceEvent.action == C.ACTION_CLOCK_IN)).scalar()
    assert n == 1                                   # recorded exactly once
    assert r1["synced"] == 1
    assert any(x.get("duplicate") for x in r2["results"])  # replay recognised as a duplicate


# --- duplicate-punch DB guard (S6) ------------------------------------------
def test_duplicate_clock_in_blocked_at_db(db, make_user):
    import pytest
    from datetime import date, datetime
    from sqlalchemy.exc import IntegrityError
    from app.models import AttendanceEvent

    emp = make_user(role=C.ROLE_EMPLOYEE)
    day = date(2026, 8, 1)
    db.add(AttendanceEvent(user_id=emp.id, date=day, time=datetime(2026, 8, 1, 0, 0), action=C.ACTION_CLOCK_IN))
    db.commit()
    # A second clock-in for the same person/day must violate the partial unique index.
    db.add(AttendanceEvent(user_id=emp.id, date=day, time=datetime(2026, 8, 1, 1, 0), action=C.ACTION_CLOCK_IN))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- manual edit must survive the nightly recompute (regression for T1) -----
def test_manual_attendance_edit_survives_recompute(db, make_user, client, auth):
    from datetime import date
    from app.services.attendance import recompute_summary
    from app.services import daily as daily_svc

    admin = make_user(role=C.ROLE_SUPER_ADMIN)
    emp = make_user(role=C.ROLE_EMPLOYEE)
    day = date(2026, 7, 20)  # a Monday (workday)

    # No punches yet -> Absent.
    s = recompute_summary(db, emp, day, commit=True)
    assert s.status == C.STATUS_ABSENT

    # Super Admin corrects the day manually.
    auth(admin)
    r = client.patch(f"/api/attendance/summary/{s.id}", json={"clock_in": "08:00", "clock_out": "17:00"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] in (C.STATUS_ON_TIME, C.STATUS_LATE)

    # The nightly job recomputes every user for the day — the edit must NOT be wiped.
    daily_svc.process_attendance(db, day)
    db.commit()
    after = recompute_summary(db, emp, day, commit=True)
    assert after.clock_in is not None
    assert after.status != C.STATUS_ABSENT
