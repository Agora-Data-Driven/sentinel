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

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..capabilities import CAP_PERMISSIONS_MANAGE, CAP_PERMISSIONS_VIEW
from ..database import get_db
from ..models import User
from ..schemas import PermissionChangesIn
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
