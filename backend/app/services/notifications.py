"""In-app notification helper. Mirrors Atrium's graceful posture — always records, never crashes."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import ADMIN_ROLES, NOTIF_ANNOUNCEMENT
from ..models import Notification, User
from . import teams


def notify(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    commit: bool = True,
) -> Notification:
    n = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    db.add(n)
    if commit:
        db.commit()
    return n


def notify_managers(
    db: Session,
    *,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    team_id: int | None = None,
    commit: bool = True,
) -> None:
    """Fan a notification out to admins + (optionally) the team lead(s) of ``team_id``.

    🔴 A lead reaches this list through ANY of their departments (2026-08-14). It used to query
    `User.team_id == team_id`, so a lead covering a second department — the case
    `models.UserTeam` exists for — was never told about that department's work: no routing
    notification, no approval request, no overdue nudge. The failure is invisible from both ends
    (nobody sees a notification that was not sent), which is exactly why it is worth widening here
    rather than at each of the eight call sites.
    """
    targets: set[int] = set()
    for u in db.execute(select(User).where(User.role.in_(ADMIN_ROLES))).scalars():
        targets.add(u.id)
    if team_id is not None:
        leads = db.execute(select(User).where(User.role == "team_lead")).scalars().all()
        targets.update(u.id for u in leads if teams.in_team(u, team_id))
    for uid in targets:
        db.add(Notification(user_id=uid, type=type, title=title, body=body, link=link))
    if commit:
        db.commit()


def broadcast(db: Session, *, title: str, body: str | None, link: str | None = None) -> int:
    """Admin announcement to every active user. Returns the count sent."""
    users = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    for u in users:
        db.add(Notification(user_id=u.id, type=NOTIF_ANNOUNCEMENT, title=title, body=body, link=link))
    db.commit()
    return len(users)
