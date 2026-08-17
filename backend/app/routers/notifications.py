"""Notifications: bell feed, mark read."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Notification, User
from ..security import get_current_user
from ..serializers import notification_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _unread(db: Session, user: User) -> int:
    """The bell's number, as ONE aggregate — and the ONE derivation of it.

    🔴 This used to `SELECT *` every unread row and take `len()` of the list, so drawing a badge that
    says "12" hydrated twelve ORM objects and somebody who had ignored the bell for a month paid for
    hundreds. COUNT(*) is the whole job.

    Both GETs below answer with this. Two endpoints reporting one number have to agree, or the badge
    changes the moment you open the panel.
    """
    return int(db.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
    ).scalar_one())


@router.get("")
def list_notifications(
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())
    if unread_only:
        q = q.where(Notification.is_read.is_(False))
    rows = db.execute(q.limit(50)).scalars().all()
    return {"unread_count": _unread(db, user), "items": [notification_dict(n) for n in rows]}


# 🔴 Registered ABOVE the `/{notif_id}` routes on purpose — the convention the gym router's
# `/routines` block documents (§5): FastAPI matches in registration order, so a literal path
# declared after a parameterised one gets swallowed by it. Nothing shadows this today (the
# `/{notif_id}` route is a PATCH), but the next GET added down there would.
@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Just the bell's number — the app shell asks for this on EVERY navigation.

    Deliberately split from `GET ""`: that endpoint serializes up to 50 notifications, which is
    work nobody needs until the panel is actually opened. The shell only wants the badge.
    """
    return {"count": _unread(db, user)}


@router.patch("/{notif_id}/read")
def mark_read(notif_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notif_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"ok": True}


@router.patch("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"ok": True}
