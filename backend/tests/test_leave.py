"""Leave: inclusive day counting, balance bootstrapping, and applying an approval to a balance."""
from __future__ import annotations

from datetime import date

from app.services import leave as leave_svc


def test_count_days_inclusive():
    assert leave_svc.count_days(date(2026, 7, 17), date(2026, 7, 17)) == 1   # single day
    assert leave_svc.count_days(date(2026, 7, 17), date(2026, 7, 19)) == 3   # inclusive span


def test_count_days_never_below_one():
    # Defensive: an inverted range still counts as at least one day.
    assert leave_svc.count_days(date(2026, 7, 19), date(2026, 7, 17)) == 1


def test_ensure_balances_creates_one_row_per_type(db, make_user, make_leave_type):
    user = make_user()
    make_leave_type(name="Vacation", annual_balance=10)
    make_leave_type(name="Sick", annual_balance=5)
    leave_svc.ensure_balances(db, user.id, year=2026)
    rows = [b for b in _all_balances(db, user.id)]
    assert len(rows) == 2
    assert {r.remaining for r in rows} == {10, 5}


def test_apply_approval_deducts_from_remaining(db, make_user, make_leave_type):
    user = make_user()
    lt = make_leave_type(name="Vacation", annual_balance=10)
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.apply_approval(db, user.id, lt.id, days=3, year=2026)
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.used == 3 and bal.remaining == 7


def test_apply_approval_never_goes_negative(db, make_user, make_leave_type):
    user = make_user()
    lt = make_leave_type(name="Vacation", annual_balance=2)
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.apply_approval(db, user.id, lt.id, days=5, year=2026)  # over-request
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.used == 5 and bal.remaining == 0


def test_unlimited_type_tracks_usage_but_not_remaining(db, make_user, make_leave_type):
    user = make_user()
    lt = make_leave_type(name="Unpaid", annual_balance=-1)  # -1 => unlimited
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.apply_approval(db, user.id, lt.id, days=4, year=2026)
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.used == 4  # remaining stays at the sentinel -1 (unlimited), usage still tracked


def test_revert_approval_restores_balance(db, make_user, make_leave_type):
    # Approve then reverse: the days must come back (the bug left the balance permanently reduced).
    user = make_user()
    lt = make_leave_type(name="Vacation", annual_balance=10)
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.apply_approval(db, user.id, lt.id, days=3, year=2026)
    leave_svc.revert_approval(db, user.id, lt.id, days=3, year=2026)
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.used == 0 and bal.remaining == 10


def test_revert_never_inflates_past_annual(db, make_user, make_leave_type):
    # A stray reversal must not push remaining above the annual grant.
    user = make_user()
    lt = make_leave_type(name="Vacation", annual_balance=10)
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.revert_approval(db, user.id, lt.id, days=4, year=2026)
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.remaining == 10 and bal.used == 0


def test_unlimited_revert_reduces_usage_only(db, make_user, make_leave_type):
    user = make_user()
    lt = make_leave_type(name="Unpaid", annual_balance=-1)
    leave_svc.ensure_balances(db, user.id, year=2026)
    leave_svc.apply_approval(db, user.id, lt.id, days=4, year=2026)
    leave_svc.revert_approval(db, user.id, lt.id, days=4, year=2026)
    db.commit()
    bal = leave_svc.get_balance(db, user.id, lt.id, 2026)
    assert bal.used == 0


def test_cannot_request_overlapping_leave(db, client, auth, make_user, make_leave_type):
    lt = make_leave_type(name="Vacation", annual_balance=10)
    emp = make_user()
    auth(emp)
    ok = client.post("/api/leave/request", json={
        "leave_type_id": lt.id, "start_date": "2026-08-03", "end_date": "2026-08-05", "reason": "trip"})
    assert ok.status_code == 200
    clash = client.post("/api/leave/request", json={
        "leave_type_id": lt.id, "start_date": "2026-08-04", "end_date": "2026-08-06", "reason": "again"})
    assert clash.status_code == 409


def test_cannot_request_more_than_balance(db, client, auth, make_user, make_leave_type):
    lt = make_leave_type(name="Vacation", annual_balance=2)
    emp = make_user()
    auth(emp)
    r = client.post("/api/leave/request", json={
        "leave_type_id": lt.id, "start_date": "2026-08-10", "end_date": "2026-08-14", "reason": "5 days"})
    assert r.status_code == 400  # 5 requested, only 2 remain


def test_cannot_self_approve_leave(db, client, auth, make_user, make_leave_type):
    from app import constants as C
    lt = make_leave_type(name="Vacation", annual_balance=10)
    lead = make_user(role=C.ROLE_TEAM_LEAD)
    auth(lead)
    r = client.post("/api/leave/request", json={
        "leave_type_id": lt.id, "start_date": "2026-08-20", "end_date": "2026-08-20", "reason": "day"})
    assert r.status_code == 200
    req_id = r.json()["id"]
    denied = client.patch(f"/api/leave/request/{req_id}", json={"status": "Approved"})
    assert denied.status_code == 403  # can't review your own request


def _all_balances(db, user_id):
    from app.models import LeaveBalance
    from sqlalchemy import select
    return db.execute(select(LeaveBalance).where(LeaveBalance.user_id == user_id)).scalars().all()
