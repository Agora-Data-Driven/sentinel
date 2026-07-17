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
from sqlalchemy import select
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
