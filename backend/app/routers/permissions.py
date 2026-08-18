"""Permissions console — read and edit which capability each role holds.

🔴 **THIS ROUTER IS DELIBERATELY NOT UNDER `/api/manage`.** The Manage console is gated by ONE
capability (`manage.console`) which a Super Admin can hand to an Admin from this very page — and if
these routes lived behind that gate, granting somebody the departments-and-leave-types console would
silently also grant them the power to grant themselves everything else. Two consoles, two
capabilities, and `permissions.manage` is `locked` so it can never be given away
(`capabilities.is_grantable`).

Reading and writing are separate capabilities on purpose: `permissions.view` is a harmless read that
answers "what can an Account Manager actually do?" — a question that previously required reading nine
routers — and it is grantable. `permissions.manage` is the write and is not.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..capabilities import CAP_PERMISSIONS_MANAGE, CAP_PERMISSIONS_VIEW
from ..database import get_db
from ..models import User
from ..schemas import PermissionChangesIn, UserPermissionChangesIn
from ..security import require_cap
from ..services import permissions as perms_svc

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@router.get("")
def get_matrix(
    user: User = Depends(require_cap(CAP_PERMISSIONS_VIEW)),
    db: Session = Depends(get_db),
):
    """The whole role x capability grid, plus which cells are editable and why not when they aren't."""
    return perms_svc.matrix(db)


@router.put("")
def put_matrix(
    payload: PermissionChangesIn,
    user: User = Depends(require_cap(CAP_PERMISSIONS_MANAGE)),
    db: Session = Depends(get_db),
):
    """Apply a batch of grants/revokes, then return the FRESH matrix.

    🔴 The response carries the re-read grid, not just an `ok` — the console renders from it. A
    refused change (see `services/permissions.set_overrides`) therefore springs visibly back with its
    reason instead of appearing to have been saved.
    """
    result = perms_svc.set_overrides(db, user, [c.model_dump() for c in payload.changes])
    return {**result, "matrix": perms_svc.matrix(db)}


@router.post("/reset")
def reset_matrix(
    user: User = Depends(require_cap(CAP_PERMISSIONS_MANAGE)),
    db: Session = Depends(get_db),
):
    """Drop every override, returning every role to the capabilities the code ships with."""
    cleared = perms_svc.reset(db, user)
    return {"cleared": cleared, "matrix": perms_svc.matrix(db)}


# ---------------- Per-person exceptions ----------------
# 🔴 These sit behind the SAME two capabilities as the role grid, not looser ones. A per-person
# exception is a permission grant by another name — "Maria may run payroll" and "Admins may run
# payroll" have identical blast radius for Maria — so anyone who can make one can already make the
# other, and splitting them would just create a quieter door to the same room.
@router.get("/people")
def list_people_overrides(
    user: User = Depends(require_cap(CAP_PERMISSIONS_VIEW)),
    db: Session = Depends(get_db),
):
    """Everyone who has at least one exception to their role, and what it is."""
    return {"people": perms_svc.people_with_overrides(db)}


@router.get("/people/{user_id}")
def get_person_matrix(
    user_id: int,
    user: User = Depends(require_cap(CAP_PERMISSIONS_VIEW)),
    db: Session = Depends(get_db),
):
    """One person's full capability list: what their role gives, and what has been changed for them."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    return perms_svc.user_matrix(db, target)


@router.put("/people/{user_id}")
def put_person_matrix(
    user_id: int,
    payload: UserPermissionChangesIn,
    user: User = Depends(require_cap(CAP_PERMISSIONS_MANAGE)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    result = perms_svc.set_user_overrides(db, user, target,
                                          [c.model_dump() for c in payload.changes])
    return {**result, "matrix": perms_svc.user_matrix(db, target)}


@router.post("/people/{user_id}/reset")
def reset_person(
    user_id: int,
    user: User = Depends(require_cap(CAP_PERMISSIONS_MANAGE)),
    db: Session = Depends(get_db),
):
    """Return one person to exactly what their role gives them."""
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Employee not found")
    cleared = perms_svc.clear_user_overrides(db, user, target)
    return {"cleared": cleared, "matrix": perms_svc.user_matrix(db, target)}


# ---------------- The audit trail ----------------
@router.get("/audit")
def permission_audit(
    user: User = Depends(require_cap(CAP_PERMISSIONS_VIEW)),
    db: Session = Depends(get_db),
):
    """The last 40 permission changes. Deliberately readable by anyone who can READ the grid.

    Seeing who moved a permission is part of understanding the grid you are looking at — a console
    that shows the current state but not how it got there sends every "why can Admin do this?"
    question to a Super Admin. It exposes nothing the grid itself does not already show.
    """
    return {"changes": perms_svc.recent_changes(db)}
