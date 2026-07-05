"""Payroll computation — turns each employee's monthly salary + the attendance/leave data already
in Sentinel into a net-pay figure for a given month (YYYY-MM). Super Admin only (enforced at the
router). Amounts are plain numbers; the UI formats them as PHP (₱). Overtime is NOT tracked.

Model (simple, transparent, editable):
  daily_rate   = monthly_salary / working_days_in_month
  deductions   = (absent_days + unpaid_leave_days) * daily_rate  +  manual_deduction
  net_pay      = monthly_salary + bonus - deductions
The Super Admin can override with a per-person bonus/deduction (stored in payroll_entries).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DailyAttendanceSummary, LeaveRequest, LeaveType, PayrollEntry, User
from . import settings as settings_svc

_WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def month_bounds(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, monthrange(y, m)[1])


def _working_days(period: str, work_days_csv: str) -> int:
    allowed = {_WD[d.strip().lower()[:3]] for d in work_days_csv.split(",") if d.strip()[:3].lower() in _WD}
    if not allowed:
        allowed = {0, 1, 2, 3, 4}
    first, last = month_bounds(period)
    return sum(1 for d in range(1, last.day + 1) if date(first.year, first.month, d).weekday() in allowed) or 22


def compute_period(db: Session, period: str) -> dict:
    smap = settings_svc.get_map(db)
    wdays = _working_days(period, smap.get("work_days", "Mon,Tue,Wed,Thu,Fri"))
    first, last = month_bounds(period)

    users = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.name)).scalars().all()
    unpaid_type_ids = {
        lt.id for lt in db.execute(select(LeaveType).where(LeaveType.name.ilike("%unpaid%"))).scalars()
    }
    rows = []
    totals = {"base": 0.0, "bonus": 0.0, "deductions": 0.0, "net": 0.0}

    for u in users:
        salary = float(u.monthly_salary or 0)
        daily = salary / wdays if wdays else 0

        summaries = db.execute(
            select(DailyAttendanceSummary).where(
                DailyAttendanceSummary.user_id == u.id,
                DailyAttendanceSummary.date >= first,
                DailyAttendanceSummary.date <= last,
            )
        ).scalars().all()
        present = sum(1 for s in summaries if s.clock_in and s.status not in ("Absent",))
        late = sum(1 for s in summaries if s.status == "Late")
        absent = sum(1 for s in summaries if s.status == "Absent")

        # Unpaid leave days overlapping the month (approved).
        unpaid_days = 0
        if unpaid_type_ids:
            for r in db.execute(
                select(LeaveRequest).where(
                    LeaveRequest.user_id == u.id,
                    LeaveRequest.status == "Approved",
                    LeaveRequest.leave_type_id.in_(unpaid_type_ids),
                    LeaveRequest.start_date <= last,
                    LeaveRequest.end_date >= first,
                )
            ).scalars():
                lo = max(r.start_date, first)
                hi = min(r.end_date, last)
                unpaid_days += max(0, (hi - lo).days + 1)

        entry = db.execute(
            select(PayrollEntry).where(PayrollEntry.user_id == u.id, PayrollEntry.period == period)
        ).scalar_one_or_none()
        bonus = float(entry.bonus) if entry else 0.0
        manual_ded = float(entry.deduction) if entry else 0.0
        note = entry.note if entry else None
        finalized = bool(entry.finalized) if entry else False

        absence_ded = round((absent + unpaid_days) * daily, 2)
        deductions = round(absence_ded + manual_ded, 2)
        net = round(salary + bonus - deductions, 2)

        totals["base"] += salary
        totals["bonus"] += bonus
        totals["deductions"] += deductions
        totals["net"] += net

        rows.append({
            "user_id": u.id, "name": u.name, "email": u.email, "role_label": None,
            "monthly_salary": salary,
            "present_days": present, "late_days": late, "absent_days": absent,
            "unpaid_leave_days": unpaid_days,
            "absence_deduction": absence_ded,
            "bonus": bonus, "deduction": manual_ded, "note": note, "finalized": finalized,
            "net_pay": net,
        })

    totals = {k: round(v, 2) for k, v in totals.items()}
    return {"period": period, "working_days": wdays, "rows": rows, "totals": totals}
