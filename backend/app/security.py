"""Authentication (JWT in an httpOnly cookie) and role-based access control (RBAC).

RBAC is enforced at the dependency layer so EVERY protected endpoint gets a real 401/403 — not
just hidden UI. Use ``require_min_role`` / ``require_roles`` in a router's ``dependencies=`` or as a
parameter dependency when you also need the user object.
"""
from __future__ import annotations

from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import sso
from .config import settings
from .constants import ADMIN_ROLES, MANAGER_ROLES, ROLE_ACCOUNT_MANAGER, ROLE_RANK, ROLE_SUPER_ADMIN
from .database import get_db
from .models import User
from .utils.time import utcnow


# --- Token helpers ---------------------------------------------------------
def create_access_token(user_id: int) -> str:
    expire = utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


def _extract_token(request: Request) -> str | None:
    # Prefer the httpOnly cookie; fall back to a Bearer header (useful for API clients / curl).
    cookie = request.cookies.get(settings.cookie_name)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


def user_from_sso(request: Request, db: Session) -> User | None:
    """The active user named by a valid portal `ag_sso` cookie, or None.

    Identity comes from the portal; authorization stays here. An email with no ACTIVE row in
    `users` gets nothing — SSO never creates a user and never grants a role (the same contract as
    the Google OAuth path). Inert unless PLATFORM_SSO_SECRET is configured.
    """
    email = sso.email_from_cookie(settings.platform_sso_secret, request.cookies.get(sso.COOKIE_NAME))
    if not email:
        return None
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    return user if (user and user.is_active) else None


# --- "Act as user" (2026-09-02) --------------------------------------------
# A SUPER ADMIN may browse Sentinel as any other active user — the whole app then answers with that
# person's board, landing page, nav and capabilities, because every dependency below resolves to the
# TARGET. Mirrors the Mastery Engine's act-as, including its one privacy rule: TIME is never written
# while acting (see `forbid_while_acting` — a minute recorded for somebody who wasn't there is a
# fabrication, which is exactly why the engine keys its minutes to the real identity too).
#
# Mechanics: the session cookie stays the REAL person's; a second cookie carries the target id and
# is INERT unless the real session resolves to a super admin — re-checked here on every request, so
# a forged or stale cookie grants nothing (and a super admin gains nothing by forging it: acting is
# only ever a NARROWING, since super_admin already holds every capability). The real person rides
# along on `request.state.impersonator` for the few places that must know (auth's /me, the audit
# rows, the time guards).

def _apply_act_as(request: Request, db: Session, user: User) -> User:
    if user.role != ROLE_SUPER_ADMIN:
        return user
    raw = request.cookies.get(settings.act_as_cookie_name)
    if not raw:
        return user
    try:
        target_id = int(raw)
    except (TypeError, ValueError):
        return user
    if target_id == user.id:
        return user
    target = db.get(User, target_id)
    # A deactivated or deleted target silently stops the act — the super admin is simply themselves
    # again, which is the safe direction. (Refusing the request would lock them out of the very
    # pages they'd use to stop acting.)
    if not target or not target.is_active:
        return user
    request.state.impersonator = user
    return target


def impersonator(request: Request) -> User | None:
    """The REAL super admin behind this request, when it is running as somebody else."""
    return getattr(request.state, "impersonator", None)


def forbid_while_acting(request: Request, what: str = "record time") -> None:
    """403 an act that must never be performed FOR somebody. Applied to the writes that fabricate a
    person's presence or effort: attendance punches, task-timer sessions, manual time entries and
    engine-session edits. Everything else stays open — acting exists so a super admin can see and
    fix a person's board, and the act-as start/stop is in the audit log."""
    real = impersonator(request)
    if real is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You're viewing Sentinel as somebody else — you can't {what} for them. "
                   "Stop acting as them first (the banner's Stop button).")


def _resolve_real(request: Request, db: Session) -> User | None:
    token = _extract_token(request)
    uid = _decode(token) if token else None
    if uid:
        user = db.get(User, uid)
        if user and user.is_active:
            return user
        return None
    # No Sentinel session — accept a portal login instead, so arriving from the portal (or being
    # embedded beside it) just works without a second sign-in.
    return user_from_sso(request, db)


# --- Current-user dependencies --------------------------------------------
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _resolve_real(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _apply_act_as(request, db, user)


def get_real_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in person, act-as IGNORED. Only auth's own routes should want this — everything
    else takes `get_current_user` so an acting super admin sees exactly what the target sees."""
    user = _resolve_real(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = _resolve_real(request, db)
    return _apply_act_as(request, db, user) if user else None


# --- RBAC guards -----------------------------------------------------------
def require_roles(*allowed: str):
    """Dependency factory: 403 unless the current user's role is one of ``allowed``."""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _guard


def require_min_role(minimum: str):
    """Dependency factory: 403 unless the current user's rank >= ``minimum``'s rank."""
    floor = ROLE_RANK[minimum]

    def _guard(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, 0) < floor:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _guard


def require_cap(cap_key: str):
    """Dependency factory: 403 unless the current user's role holds the named CAPABILITY.

    The named-capability guard, and the one to reach for in new code. `require_min_role` /
    `require_roles` above still exist and are still correct — they are the right tool for a gate
    whose answer is genuinely "this rung of the ladder and up" and that nobody should be able to
    reassign. Everything that IS reassignable goes through here, because this is what the Super
    Admin's Permissions console can actually move (`app/capabilities.py`).

        router = APIRouter(prefix="/api/thing",
                           dependencies=[Depends(require_cap(CAP_THING_MANAGE))])

        @router.patch("/{id}")
        def edit(id: int, user: User = Depends(require_cap(CAP_THING_EDIT)), ...): ...

    🔴 The capability key must exist in the registry — `permissions.has_cap` answers False for an
    unknown one, so a typo CLOSES the endpoint rather than opening it.
    """

    def _guard(user: User = Depends(get_current_user)) -> User:
        from .services import permissions as perms_svc

        if not perms_svc.has_cap(user, cap_key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _guard


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def is_manager(user: User) -> bool:
    return user.role in MANAGER_ROLES


def is_account_manager(user: User) -> bool:
    return user.role == ROLE_ACCOUNT_MANAGER
