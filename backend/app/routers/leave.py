"""Leave Management: types, balances, requests, approvals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import (
    LEAVE_APPROVED,
    LEAVE_PENDING,
    LEAVE_REJECTED,
    NOTIF_APPROVAL,
    ROLE_SUPER_ADMIN,
    ROLE_TEAM_LEAD,
)


def _remaining(db: Session, user_id: int, lt: LeaveType, year: int) -> float:
    """Days left for a balance-limited leave type this year (unlimited types return infinity)."""
    if lt.annual_balance < 0:
        return float("inf")
    leave_svc.ensure_balances(db, user_id, year, commit=False)
    bal = leave_svc.get_balance(db, user_id, lt.id, year)
    return bal.remaining if bal else lt.annual_balance
from ..database import get_db
from ..models import LeaveBalance, LeaveRequest, LeaveType, User
from ..schemas import LeaveDecisionIn, LeaveRequestIn
from ..security import get_current_user, require_min_role
from ..serializers import leave_balance_dict, leave_request_dict, leave_type_dict
from ..services import audit
from ..services import leave as leave_svc
from ..services import notifications as notif
from ..utils.time import today_ph, utcnow

router = APIRouter(prefix="/api/leave", tags=["leave"])


@router.get("/types")
def types(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(LeaveType).order_by(LeaveType.id)).scalars().all()
    return [leave_type_dict(lt) for lt in rows]


@router.get("/balance")
def balance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    year = today_ph().year
    leave_svc.ensure_balances(db, user.id, year)
    rows = db.execute(
        select(LeaveBalance).where(LeaveBalance.user_id == user.id, LeaveBalance.year == year)
    ).scalars().all()
    return [leave_balance_dict(b, db.get(LeaveType, b.leave_type_id)) for b in rows]


@router.get("/my")
def my_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(LeaveRequest).where(LeaveRequest.user_id == user.id).order_by(LeaveRequest.created_at.desc())
    ).scalars().all()
    return [leave_request_dict(r, db) for r in rows]


@router.post("/request")
def create_request(payload: LeaveRequestIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lt = db.get(LeaveType, payload.leave_type_id)
    if not lt:
        raise HTTPException(status_code=404, detail="Leave type not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="End date is before start date")
    days = leave_svc.count_days(payload.start_date, payload.end_date)

    # L3 — no overlapping leave: reject if a pending/approved request already covers any of these days.
    clash = db.execute(
        select(LeaveRequest).where(
            LeaveRequest.user_id == user.id,
            LeaveRequest.status.in_([LEAVE_PENDING, LEAVE_APPROVED]),
            LeaveRequest.start_date <= payload.end_date,
            LeaveRequest.end_date >= payload.start_date,
        )
    ).scalars().first()
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"You already have a {clash.status.lower()} leave from {clash.start_date} to {clash.end_date} that overlaps these dates.",
        )

    # L2 — balance check: don't let someone request more of a limited type than they have left.
    remaining = _remaining(db, user.id, lt, payload.start_date.year)
    if days > remaining:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough {lt.name}: {remaining:g} day(s) remaining, but {days} requested.",
        )

    req = LeaveRequest(
        user_id=user.id, leave_type_id=lt.id, start_date=payload.start_date,
        end_date=payload.end_date, total_days=days, reason=payload.reason, status=LEAVE_PENDING,
    )
    db.add(req)
    db.flush()  # assign req.id without committing — one atomic commit at the end
    notif.notify_managers(
        db, type=NOTIF_APPROVAL, title=f"{lt.name} request from {user.name} ({days}d)",
        body=payload.reason, link="/leave", team_id=user.team_id, commit=False,
    )
    audit.record(db, actor_id=user.id, table_name="leave_requests", record_id=req.id, action="create",
                 new={"type": lt.name, "days": days}, commit=False)
    db.commit()
    return leave_request_dict(req, db)


@router.get("/requests")
def all_requests(
    status: str | None = Query(None),
    reviewer: User = Depends(require_min_role(ROLE_TEAM_LEAD)),
    db: Session = Depends(get_db),
):
    q = select(LeaveRequest).order_by(LeaveRequest.created_at.desc())
    if status:
        q = q.where(LeaveRequest.status == status)
    rows = db.execute(q).scalars().all()
    if reviewer.role == ROLE_TEAM_LEAD:
        rows = [r for r in rows if (db.get(User, r.user_id) or User()).team_id == reviewer.team_id]
    return [leave_request_dict(r, db) for r in rows]


@router.patch("/request/{req_id}")
def decide(req_id: int, payload: LeaveDecisionIn, reviewer: User = Depends(require_min_role(ROLE_TEAM_LEAD)), db: Session = Depends(get_db)):
    req = db.get(LeaveRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if payload.status not in (LEAVE_APPROVED, LEAVE_REJECTED):
        raise HTTPException(status_code=400, detail="Status must be Approved or Rejected")
    # L4 — no self-approval: a reviewer can't decide their own request (Super Admin is the top
    # authority and exempt, so a solo owner isn't deadlocked).
    if reviewer.id == req.user_id and reviewer.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="You can't review your own leave request — ask another approver.")
    old = req.status
    # L2 — don't approve beyond the remaining balance for a limited type.
    if payload.status == LEAVE_APPROVED and old != LEAVE_APPROVED:
        lt = db.get(LeaveType, req.leave_type_id)
        remaining = _remaining(db, req.user_id, lt, req.start_date.year) if lt else 0
        if req.total_days > remaining:
            raise HTTPException(
                status_code=400,
                detail=f"Can't approve: only {remaining:g} {lt.name if lt else ''} day(s) remain, {req.total_days} requested.",
            )
    req.status = payload.status
    req.reviewed_by_id = reviewer.id
    req.reviewed_at = utcnow()
    if payload.status == LEAVE_APPROVED and old != LEAVE_APPROVED:
        leave_svc.apply_approval(db, req.user_id, req.leave_type_id, req.total_days, req.start_date.year)
    elif old == LEAVE_APPROVED and payload.status != LEAVE_APPROVED:
        # Reversing an approval must give the days back — otherwise the balance leaks permanently.
        leave_svc.revert_approval(db, req.user_id, req.leave_type_id, req.total_days, req.start_date.year)
    notif.notify(
        db, user_id=req.user_id, type=NOTIF_APPROVAL,
        title=f"Your leave request was {payload.status.lower()}",
        body=f"{req.total_days} day(s) from {req.start_date}", link="/leave", commit=False,
    )
    audit.record(db, actor_id=reviewer.id, table_name="leave_requests", record_id=req.id, action="decide",
                 old={"status": old}, new={"status": payload.status}, commit=False)
    db.commit()  # status change + balance + notification + audit all commit together
    return leave_request_dict(req, db)
