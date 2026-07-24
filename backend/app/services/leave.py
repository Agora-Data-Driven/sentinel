"""Leave logic: day counting, balance bootstrapping, and applying an approval to a balance."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LeaveBalance, LeaveType
from ..utils.time import today_ph


def count_days(start: date, end: date) -> int:
    """Inclusive calendar-day span (MVP counts weekends too; refine per policy later)."""
    return max(1, (end - start).days + 1)


def ensure_balances(db: Session, user_id: int, year: int | None = None, commit: bool = True) -> None:
    """Make sure the user has a balance row for every leave type this year."""
    year = year or today_ph().year
    types = db.execute(select(LeaveType)).scalars().all()
    existing = {
        b.leave_type_id
        for b in db.execute(
            select(LeaveBalance).where(
                LeaveBalance.user_id == user_id, LeaveBalance.year == year
            )
        ).scalars()
    }
    for lt in types:
        if lt.id in existing:
            continue
        db.add(
            LeaveBalance(
                user_id=user_id,
                leave_type_id=lt.id,
                year=year,
                used=0.0,
                remaining=lt.annual_balance,  # -1 => unlimited
            )
        )
    if commit:
        db.commit()


def get_balance(db: Session, user_id: int, leave_type_id: int, year: int) -> LeaveBalance | None:
    return db.execute(
        select(LeaveBalance).where(
            LeaveBalance.user_id == user_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
    ).scalar_one_or_none()


def apply_approval(db: Session, user_id: int, leave_type_id: int, days: float, year: int) -> None:
    """Deduct approved days from the matching balance (unlimited types stay untouched)."""
    bal = get_balance(db, user_id, leave_type_id, year)
    if not bal:
        ensure_balances(db, user_id, year, commit=False)
        bal = get_balance(db, user_id, leave_type_id, year)
    if not bal:
        return
    lt = db.get(LeaveType, leave_type_id)
    if lt and lt.annual_balance < 0:  # unlimited (e.g. Unpaid) — track usage only
        bal.used = (bal.used or 0) + days
        return
    bal.used = (bal.used or 0) + days
    bal.remaining = max(0.0, (bal.remaining or 0) - days)


def revert_approval(db: Session, user_id: int, leave_type_id: int, days: float, year: int) -> None:
    """Credit days back when a previously-approved leave is rejected/cancelled (mirror of apply_approval)."""
    bal = get_balance(db, user_id, leave_type_id, year)
    if not bal:
        return
    bal.used = max(0.0, (bal.used or 0) - days)
    lt = db.get(LeaveType, leave_type_id)
    if lt and lt.annual_balance < 0:  # unlimited — only usage was tracked, no remaining to restore
        return
    restored = (bal.remaining or 0) + days
    # Don't let a restore inflate the balance past the annual grant.
    bal.remaining = min(lt.annual_balance, restored) if lt else restored
