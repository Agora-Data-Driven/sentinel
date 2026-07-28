"""Shared transport for every Sentinel -> Atrium internal call.

Server-to-server HMAC-SHA256 over "{purpose}:{ts}" with the shared `platform-sso-key`, sent as
X-Academy-Ts / X-Academy-Sig -- the same scheme `sentinel_directory.py` uses in the other direction
and mastery-engine uses against `/api/internal/people`. Extracted out of `atrium_tasks.py` so a
second bridge (`atrium_watcher.py`) doesn't re-implement the same signing.

EVERYTHING here is best-effort and fail-SOFT: an unset secret, a missing URL, a timeout, a non-200
or a malformed body all degrade to "nothing from Atrium" in the caller. An Atrium outage must never
break a Sentinel page.

STDLIB ONLY (urllib, not requests) -- see atrium_tasks.py's docstring for why.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import settings

log = logging.getLogger(__name__)

READ_TIMEOUT = 10
WRITE_TIMEOUT = 30


def base_url() -> str:
    """The portal's origin, or "" when unconfigured (every bridge stays off)."""
    url = (getattr(settings, "atrium_api_url", "") or "").strip()
    if not url:
        # Fall back to the portal login URL's origin, so a deploy that already knows where the
        # portal lives needs no extra setting.
        login = (getattr(settings, "portal_login_url", "") or "").strip()
        if login:
            url = login.split("/auth/")[0].split("/login")[0]
    return url.rstrip("/")


def _headers(purpose: str) -> dict | None:
    secret = (settings.platform_sso_secret or "").strip()
    if not secret:
        return None
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": sig}


def enabled() -> bool:
    """True when both the shared secret and the portal URL are configured."""
    return bool((settings.platform_sso_secret or "").strip() and base_url())


def call(purpose: str, path: str, params: dict | None = None,
         body: dict | None = None, timeout: int | None = None) -> tuple[int, dict]:
    """One signed request. Returns (status_code, parsed_json); (0, {}) if it never left the ground.

    Never raises -- every caller degrades instead, because an Atrium outage must not break the
    calling Sentinel page."""
    headers = _headers(purpose)
    base = base_url()
    if not headers or not base:
        return 0, {}
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=(timeout or READ_TIMEOUT)) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        # A non-2xx still carries a body worth surfacing (e.g. a completion guard).
        try:
            return exc.code, json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return exc.code, {}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.warning("atrium %s call failed: %s", purpose, exc)
        return 0, {}
