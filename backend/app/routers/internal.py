"""Internal service-to-service endpoints (no user session).

These are called by sister apps in the Agora ecosystem (e.g. the mastery engine's
Academy admin, which needs the Sentinel people list to offer a name dropdown).
They are gated by an HMAC signature over a timestamp, using the SAME shared secret
the portal signs `ag_sso` with (Secret Manager `platform-sso-key`), which both
services already mount. No new secret, no CORS, no browser credentials: only a
caller holding the shared secret can read these, and the timestamp window blocks
replay. If the secret isn't configured (local dev), the endpoint is disabled.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi import Depends

from ..config import settings
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/internal", tags=["internal"])

# How far apart the caller's clock and ours may be (replay window).
_MAX_SKEW_SECONDS = 300


def _verify(ts: str | None, sig: str | None, purpose: str) -> None:
    secret = (settings.platform_sso_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="internal auth not configured")
    if not ts or not sig:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing signature")
    try:
        skew = abs(time.time() - int(ts))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad timestamp")
    if skew > _MAX_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stale request")
    expected = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad signature")


@router.get("/people")
def internal_people(
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Active users as {email, name, role} — for a sister app's person picker."""
    _verify(x_academy_ts, x_academy_sig, "academy-people")
    rows = db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.name)
    ).scalars().all()
    return {
        "people": [
            {"email": u.email, "name": u.name or u.email, "role": u.role}
            for u in rows
        ]
    }


@router.get("/user-lookup")
def internal_user_lookup(
    email: str,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Is `email` a Sentinel user, and is the account active?

    This is what makes Sentinel the source of truth for "who may sign in with Google": the portal
    (the one app that runs the OAuth flow) calls this on a verified email it doesn't already know,
    and signs the caller in when we say the user is active. Adding someone via People → Add Employee
    is therefore all it takes to enable their Google login; deactivating them blocks it immediately.

    Returns identity only ({found, active, name, role}) — never anything else. HMAC-gated exactly
    like /people (shared `platform-sso-key`, timestamp replay window), so only a caller holding the
    secret can probe the directory.
    """
    _verify(x_academy_ts, x_academy_sig, "user-lookup")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None:
        return {"found": False, "active": False, "name": "", "role": ""}
    return {
        "found": True,
        "active": bool(user.is_active),
        "name": user.name or user.email,
        "role": user.role,
    }
