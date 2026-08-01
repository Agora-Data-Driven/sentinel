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
from ..services import development as dev_svc
from ..services import mentor_search as mentor_svc

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


@router.get("/holistic-profile")
def internal_holistic_profile(
    email: str,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """A compact digest of `email`'s whole-person development, for the Mastery Engine AI coach.

    The coach calls this server-to-server (HMAC-gated, shared platform-sso-key) so the SAME assistant
    that knows the worker's learning can also speak to their body-fat/PRs, career goals, required
    reading, and personal obstacles. It's always the user's OWN data (the coach acts on their behalf),
    so no manager check applies here. Unknown/inactive email → an empty profile (the coach then simply
    has no holistic context and behaves as before).
    """
    _verify(x_academy_ts, x_academy_sig, "holistic-profile")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "profile": None}
    return {"found": True, "profile": dev_svc.holistic_digest(db, user)}


@router.get("/growth-detail")
def internal_growth_detail(
    email: str,
    ids: str = "",
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Full bodies for specific growth-journal entries — the "big" half of small-to-big retrieval.

    `holistic-profile` hands the coach a COMPLETE index of the worker's journal (every entry's title,
    uncapped) but no bodies, because the journal grows without bound and most turns need none of it.
    When a turn does bear on an entry, the coach names its ids here and gets the text back WHOLE.

    Why the index is complete and only the bodies are lazy: the coach decides "you have no note about
    X" by not seeing X in the index. If the index were sampled, that inference would be a confident
    lie — the failure that made a 600-char cap on `other_info` deny a list the worker was looking at
    on their own screen. A retrieval MISS here is recoverable (the title is still listed, so the
    coach can say "you have a note called X I haven't opened"); a missing title is not.

    `ids` is a comma-separated list, capped at `MAX_GROWTH_DETAIL_IDS` entries per call — a limit on
    the request, never on any entry's text. Entries are scoped to the owner, so unknown or
    other-people's ids are simply absent from the response rather than an error.

    Always the user's OWN journal (the coach acts on their behalf), so no manager check applies.
    Unknown/inactive email → an empty result and the coach stays ungrounded, exactly as before.
    """
    _verify(x_academy_ts, x_academy_sig, "growth-detail")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "entries": []}
    wanted: list[int] = []
    for part in (ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            wanted.append(int(part))
        except ValueError:
            # A malformed id is the caller's bug, not a reason to fail the worker's whole turn —
            # skip it and serve whatever else was asked for.
            continue
    return {"found": True, "entries": dev_svc.growth_details(db, user.id, wanted)}


@router.get("/mentor-search")
def internal_mentor_search(
    email: str,
    q: str = "",
    mentor: str = "",
    limit: int = mentor_svc.DEFAULT_LIMIT,
    x_academy_ts: str | None = Header(default=None),
    x_academy_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """The passages from `email`'s Mentor Library that bear on `q` — retrieval for the AI coach.

    This is what makes "what would Nick say about my plan?" and "act as Nick and mentor me"
    answerable. The library is far too large to hand over (one creator can be ~1M words), and the
    holistic digest could only ever list titles — so the coach asks this instead and gets back the
    handful of relevant passages to reason from.

    `mentor` narrows to one person and is matched loosely ("nick" → "Nick Saraev"), because that is
    how people actually ask. `matched_mentor` lets the caller distinguish "that mentor isn't in
    their library" from "that mentor never covered this" — two answers the coach must never blur.

    Always the user's OWN library (the coach acts on their behalf), so no manager check applies.
    Unknown/inactive email → an empty result and the coach simply stays ungrounded, as before.
    """
    _verify(x_academy_ts, x_academy_sig, "mentor-search")
    norm = (email or "").strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == norm)
    ).scalars().first() if norm else None
    if user is None or not user.is_active:
        return {"found": False, "mentors": [], "mentor": "", "matched_mentor": False,
                "excerpts": []}
    out = mentor_svc.search(db, user.id, q, mentor=mentor, limit=limit)
    out["found"] = True
    out["mentors"] = mentor_svc.roster(db, user.id)
    return out
