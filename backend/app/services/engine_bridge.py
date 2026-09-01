"""Shared transport for every Sentinel -> Mastery Engine internal call.

Server-to-server HMAC-SHA256 over "{purpose}:{ts}" with the shared `platform-sso-key`, sent as
X-Academy-Ts / X-Academy-Sig -- the same scheme `atrium_bridge.py` uses toward Atrium and the
engine uses back toward `routers/internal.py`. Extracted so a second engine call doesn't
re-implement the signing that `routers/meta.py` had inline.

Purposes in use: `enrollment-progress` (one person's rings), `team-progress` (the whole roster's
rollup + attempt window, behind the admin team panel), `time-spent` / `time-detail` (minutes actively
spent in the engine — the Overview's time strip and the admin team-time table, `services/time_spent.py`),
`time-edit` (the one WRITE: remove recorded minutes — the learner's honesty edit; `post()` below).

EVERYTHING here is best-effort and fail-SOFT AT THE TRANSPORT: an unset secret, a missing URL, a
timeout, a non-200 or a malformed body all return (status, {}) rather than raising. But callers
must NOT read an empty body as "this person has no progress" -- see `team_growth.py`, which keeps
"the engine didn't answer" and "they scored zero" as two different states all the way to the UI.

STDLIB ONLY (urllib, not requests) -- matching atrium_bridge.py, so the runtime image needs no
extra dependency for a bridge that must never be the reason a page fails.
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
# The team rollup reads the shared catalogue plus every person's stats, so it is legitimately
# slower than a single-person call -- and it is fetched behind a cache, not per keystroke.
TEAM_TIMEOUT = 30


def base_url() -> str:
    """The engine's origin, or "" when unconfigured (every engine bridge then stays off)."""
    return (settings.skill_mastery_url or "").strip().rstrip("/")


def _headers(purpose: str) -> dict | None:
    secret = (settings.platform_sso_secret or "").strip()
    if not secret:
        return None
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{purpose}:{ts}".encode(), hashlib.sha256).hexdigest()
    return {"X-Academy-Ts": ts, "X-Academy-Sig": sig}


def enabled() -> bool:
    """True when both the shared secret and the engine URL are configured."""
    return bool((settings.platform_sso_secret or "").strip() and base_url())


def post(purpose: str, path: str, body: dict, timeout: int | None = None) -> tuple[int, dict, str]:
    """One signed POST with a JSON body. Same contract as `call`: (status_code, parsed_json, error),
    status 0 when the request never left, never raises. Used for the engine's few WRITES."""
    headers = _headers(purpose)
    base = base_url()
    if not headers:
        return 0, {}, "the shared platform key is not configured"
    if not base:
        return 0, {}, "the Mastery Engine URL is not configured"
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=(timeout or READ_TIMEOUT)) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {}), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (json.loads(exc.read().decode("utf-8", "replace")) or {}).get("error", "")
        except Exception:
            detail = ""
        log.warning("engine %s post failed: HTTP %s %s", purpose, exc.code, detail)
        return exc.code, {}, f"the Mastery Engine answered {exc.code}" + (f" ({detail})" if detail else "")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.warning("engine %s post failed: %s", purpose, exc)
        return 0, {}, f"couldn't reach the Mastery Engine ({str(exc)[:80]})"


def call(purpose: str, path: str, params: dict | None = None,
         timeout: int | None = None) -> tuple[int, dict, str]:
    """One signed GET. Returns (status_code, parsed_json, error).

    `status_code` is 0 when the request never left the ground (no secret, no URL, DNS, timeout).
    `error` is a short human sentence, "" on success -- callers surface it instead of pretending
    the engine answered with nothing. Never raises.
    """
    headers = _headers(purpose)
    base = base_url()
    if not headers:
        return 0, {}, "the shared platform key is not configured"
    if not base:
        return 0, {}, "the Mastery Engine URL is not configured"
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=(timeout or READ_TIMEOUT)) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {}), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = (json.loads(exc.read().decode("utf-8", "replace")) or {}).get("error", "")
        except Exception:
            detail = ""
        log.warning("engine %s call failed: HTTP %s %s", purpose, exc.code, detail)
        return exc.code, {}, f"the Mastery Engine answered {exc.code}" + (f" ({detail})" if detail else "")
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        log.warning("engine %s call failed: %s", purpose, exc)
        return 0, {}, f"couldn't reach the Mastery Engine ({str(exc)[:80]})"
