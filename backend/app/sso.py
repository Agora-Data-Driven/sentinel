"""Central portal single-sign-on (`ag_sso`) — verifier only.

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
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

COOKIE_NAME = "ag_sso"


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


def mint(secret: str, subject: str, clients=("*",), ttl_seconds: int = 60 * 60 * 12,
         now: float | None = None) -> str:
    """Mint a cookie exactly as the portal does. Sentinel never calls this in production —
    it exists so the tests can exercise the verifier against a real signature."""
    issued = int(now if now is not None else time.time())
    payload = {"sub": subject, "clients": list(clients), "iat": issued, "exp": issued + int(ttl_seconds)}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return "%s.%s" % (payload_b64, _sign(secret, payload_b64))
