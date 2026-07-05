"""Payroll / Accounting — Super Admin ONLY. Computes each employee's net pay for a month from the
attendance, overtime, and leave data already in Sentinel, with editable per-person bonus/deduction.

Every route is gated by ``require_roles(ROLE_SUPER_ADMIN)`` so salaries are never exposed to other
roles — not just hidden in the UI. All salary/bonus changes are written to the audit trail.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ROLE_SUPER_ADMIN
from ..database import get_db
from ..models import PayrollEntry, User
from ..schemas import PayrollAdjustIn, PayrollFinalizeIn, SalaryIn
from ..security import require_roles
from ..services import audit
from ..services import payroll as payroll_svc
from ..utils.csv_export import csv_response

router = APIRouter(prefix="/api/payroll", tags=["payroll"])

_SA = require_roles(ROLE_SUPER_ADMIN)


def _valid_period(period: str) -> str:
    try:
        y, m = int(period[:4]), int(period[5:7])
        date(y, m, 1)
        if period[4] != "-" or not (1 <= m <= 12):
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    return f"{y:04d}-{m:02d}"


@router.get("")
def get_payroll(
    period: str = Query(...),
    export: str | None = Query(None),
    _: User = Depends(_SA),
    db: Session = Depends(get_db),
):
    period = _valid_period(period)
    result = payroll_svc.compute_period(db, period)
    if export == "csv":
        headers = ["Employee", "Email", "Monthly Salary", "Present", "Absent",
                   "Unpaid Leave", "Bonus", "Deduction", "Net Pay", "Finalized"]
        rows = [
            [r["name"], r["email"], r["monthly_salary"], r["present_days"], r["absent_days"],
             r["unpaid_leave_days"], r["bonus"],
             r["deduction"] + r["absence_deduction"], r["net_pay"], "Yes" if r["finalized"] else "No"]
            for r in result["rows"]
        ]
        return csv_response(f"sentinel-payroll-{period}.csv", headers, rows)
    return result


@router.put("/salary/{user_id}")
def set_salary(
    user_id: int,
    payload: SalaryIn,
    admin: User = Depends(_SA),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old = user.monthly_salary
    user.monthly_salary = payload.monthly_salary
    audit.record(db, actor_id=admin.id, table_name="users", record_id=user_id, action="set_salary",
                 old={"monthly_salary": old}, new={"monthly_salary": payload.monthly_salary}, commit=False)
    db.commit()
    return {"ok": True, "user_id": user_id, "monthly_salary": user.monthly_salary}


def _get_entry(db: Session, user_id: int, period: str) -> PayrollEntry | None:
    return db.execute(
        select(PayrollEntry).where(PayrollEntry.user_id == user_id, PayrollEntry.period == period)
    ).scalar_one_or_none()


@router.post("/adjust/{user_id}")
def adjust(
    user_id: int,
    payload: PayrollAdjustIn,
    admin: User = Depends(_SA),
    db: Session = Depends(get_db),
):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    period = _valid_period(payload.period)
    entry = _get_entry(db, user_id, period)
    old = {"bonus": entry.bonus, "deduction": entry.deduction, "note": entry.note} if entry else None
    if entry:
        if entry.finalized:
            raise HTTPException(status_code=409, detail="Period is finalized - unlock it first")
        entry.bonus = payload.bonus
        entry.deduction = payload.deduction
        entry.note = payload.note
    else:
        entry = PayrollEntry(user_id=user_id, period=period, bonus=payload.bonus,
                             deduction=payload.deduction, note=payload.note)
        db.add(entry)
    audit.record(db, actor_id=admin.id, table_name="payroll_entries", record_id=f"{user_id}:{period}",
                 action="adjust", old=old,
                 new={"bonus": payload.bonus, "deduction": payload.deduction, "note": payload.note},
                 commit=False)
    db.commit()
    return {"ok": True}


@router.post("/finalize/{user_id}")
def finalize(
    user_id: int,
    payload: PayrollFinalizeIn,
    admin: User = Depends(_SA),
    db: Session = Depends(get_db),
):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    period = _valid_period(payload.period)
    entry = _get_entry(db, user_id, period)
    if not entry:
        entry = PayrollEntry(user_id=user_id, period=period)
        db.add(entry)
    entry.finalized = payload.finalized
    audit.record(db, actor_id=admin.id, table_name="payroll_entries", record_id=f"{user_id}:{period}",
                 action="finalize", new={"finalized": payload.finalized}, commit=False)
    db.commit()
    return {"ok": True, "finalized": entry.finalized}
