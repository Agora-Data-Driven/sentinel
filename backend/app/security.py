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
from .constants import ADMIN_ROLES, MANAGER_ROLES, ROLE_ACCOUNT_MANAGER, ROLE_RANK
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


# --- Current-user dependencies --------------------------------------------
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    uid = _decode(token) if token else None
    if uid:
        user = db.get(User, uid)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        return user
    # No Sentinel session — accept a portal login instead, so arriving from the portal (or being
    # embedded beside it) just works without a second sign-in.
    user = user_from_sso(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = _extract_token(request)
    uid = _decode(token) if token else None
    if uid:
        user = db.get(User, uid)
        if user and user.is_active:
            return user
    return user_from_sso(request, db)


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


def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES


def is_manager(user: User) -> bool:
    return user.role in MANAGER_ROLES


def is_account_manager(user: User) -> bool:
    return user.role == ROLE_ACCOUNT_MANAGER
