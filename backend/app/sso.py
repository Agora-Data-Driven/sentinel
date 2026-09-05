"""Central portal single-sign-on (`ag_sso`) — verifier, plus ONE narrow minter.

The Agora portal (portal.agoradatadriven.com) is the ONE front door. On a successful portal login it
mints an `ag_sso` cookie: an HMAC-SHA256-signed JSON payload, scoped to `.agoradatadriven.com` so it
is presented to every sibling host. This module verifies that cookie so a portal login is trusted
here too — the same way the mastery engine and every client dashboard already trust it.

This is a port of the portal's `platform_sso.py` (the signer of record); the wire format must match
it byte for byte, so keep the two in step:
    cookie = base64url(json_payload) + "." + base64url(hmac_sha256(secret, payload_b64))
    payload = {"sub": <email>, "clients": [...], "iat": <int>, "exp": <int>}

WHAT THIS DOES NOT DO — deliberately:
  The portal's own helper also checks that the payload's client list covers the calling dashboard.
  Sentinel is not a client dashboard: it is the internal ops tool, and the cookie only ever tells us
  WHO the visitor is. Authorization stays exactly where it already lives — the `users` table. An
  email with no active row gets in nowhere, no matter what the portal signed. This mirrors the
  existing Google OAuth path (identity from the provider, authorization from our own table), so SSO
  can never create a user or widen a role.

Fail-CLOSED everywhere: a missing secret, a malformed/forged/expired cookie, or ANY unexpected error
yields None, so SSO can only ever ADD a way in for someone who already has an account.

MINTING (2026-09-05): Sentinel now signs this cookie in exactly one place — `routers/auth.me`
`_refresh_shared_cookie` — and only for a person who ALREADY holds a valid Sentinel session and has
LOST the portal's cookie. It never creates identity: the subject is the signed-in user's own email,
so this widens nothing the session did not already prove. Why it exists: the cookie lives 12h and the
portal re-mints it only when the portal itself is visited, but staff live in Sentinel (7-day session)
and never touch the portal — so 12h after signing in, the Mastery Engine frames inside Sentinel (the
Professional/Philosophical/Spiritual tabs and the Coach) fell through their auth ladder and drew
their own login form inside ours. The wire format is the portal's; a client list is the one field
the portal knows better (its per-client grants), which is why a LIVE portal cookie is never replaced.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

COOKIE_NAME = "ag_sso"
# The portal's scope: a parent-domain cookie, which any *.agoradatadriven.com host may set. Keep both
# of these in step with atrium's platform_sso.py (COOKIE_DOMAIN there, DEFAULT_TTL_SECONDS 12h).
COOKIE_DOMAIN = ".agoradatadriven.com"
DEFAULT_TTL_SECONDS = 60 * 60 * 12


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, payload_b64: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64e(mac.digest())


def verify(secret: str, raw: str | None, now: float | None = None) -> dict | None:
    """The cookie's payload if it is validly signed and unexpired, else None."""
    if not secret or not raw or "." not in raw:
        return None
    try:
        payload_b64, sig = raw.split(".", 1)
        # Constant-time — never compare a MAC with ==.
        if not hmac.compare_digest(_sign(secret, payload_b64), sig):
            return None
        payload = json.loads(_b64d(payload_b64))
        if int(payload.get("exp", 0)) < int(now if now is not None else time.time()):
            return None
        return payload
    except Exception:
        # Any parse/decode error -> reject. SSO must never raise into the auth path.
        return None


def email_from_cookie(secret: str, raw: str | None, now: float | None = None) -> str:
    """The verified portal email (`sub`), normalised, or "" when the cookie isn't trustworthy."""
    payload = verify(secret, raw, now)
    if not payload:
        return ""
    return str(payload.get("sub") or "").strip().lower()


def mint(secret: str, subject: str, clients=("*",), ttl_seconds: int = DEFAULT_TTL_SECONDS,
         now: float | None = None) -> str:
    """Mint a cookie exactly as the portal does.

    Production has ONE caller — `routers/auth._refresh_shared_cookie` (see the module docstring) —
    and the tests use it to exercise the verifier against a real signature."""
    issued = int(now if now is not None else time.time())
    payload = {"sub": subject, "clients": list(clients), "iat": issued, "exp": issued + int(ttl_seconds)}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return "%s.%s" % (payload_b64, _sign(secret, payload_b64))
