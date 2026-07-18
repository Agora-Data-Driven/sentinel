"""HTTP hardening middleware: security response headers + lightweight rate limiting.

Both are pure-stdlib (no extra dependencies) and self-contained so routers stay untouched.

- ``SecurityHeadersMiddleware`` adds CSP / anti-clickjacking / MIME-sniffing / referrer /
  permissions headers to every response, and HSTS when we're actually behind HTTPS.
- ``RateLimitMiddleware`` applies a per-IP sliding-window cap to the endpoints worth brute-forcing
  (password login and QR-token scanning). It is per-process, so on multi-instance Cloud Run it's a
  basic abuse brake rather than a global quota — good enough to blunt scripted attacks.
"""
from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import settings

# Content-Security-Policy tuned to what the frontend actually loads:
# - no inline <script> anywhere -> script-src can stay strict 'self'
# - Google Fonts stylesheet + a few inline style="" attrs -> style-src allows 'unsafe-inline' + gfonts
# - font files come from fonts.gstatic.com
# - QR PNGs / kiosk camera canvas -> img-src allows data: and blob:
# - PWA service worker -> worker-src 'self'
# - frame-src: North Star embeds a same-origin page; the Academy tab embeds the mastery engine on
#   an *.agoradatadriven.com host (see SKILL_MASTERY_URL) — both must be allowed to load in an iframe.
# - frame-ancestors: who may frame US. Sentinel frames its own same-origin who-we-are.html and is
#   meant to live inside the Agora portal, so this is driven by CSP_FRAME_ANCESTORS (not a hard
#   'none', which would break the North Star embed).
def _csp() -> str:
    return (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "worker-src 'self'; "
        "manifest-src 'self'; "
        "frame-src 'self' https://*.agoradatadriven.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        f"frame-ancestors {settings.csp_frame_ancestors}"
    )


# The Academy tab embeds the mastery engine (a cross-origin *.agoradatadriven.com host) in an iframe,
# and its Study Assistant uses the microphone for voice input. A cross-origin iframe can only get the
# mic if BOTH the frame carries allow="microphone" AND the top-level document *delegates* the feature
# to that origin here. `microphone=()` (empty allowlist) blocks it for everyone — including the frame —
# so the mic silently fails with no prompt. Permissions-Policy origins must be exact (no wildcards),
# so we derive the mastery origin from SKILL_MASTERY_URL. Camera stays self-only for the kiosk.
def _permissions_policy() -> str:
    parts = urlsplit(settings.skill_mastery_url)
    mastery_origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    mic_allow = f'(self "{mastery_origin}")' if mastery_origin else "(self)"
    return f"camera=(self), microphone={mic_allow}, geolocation=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", _csp())
        # frame-ancestors (above) is the source of truth and, per spec, browsers ignore X-Frame-
        # Options when it's present. Keep XFO only as legacy defence-in-depth, and don't let a hard
        # DENY here contradict a frame-ancestors that allows framing: SAMEORIGIN unless we forbid all.
        h.setdefault("X-Frame-Options", "DENY" if settings.csp_frame_ancestors == "'none'" else "SAMEORIGIN")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Kiosk needs the camera on its own origin; the mic is delegated to the embedded mastery
        # engine so the Academy Study Assistant's voice input works inside its iframe.
        h.setdefault("Permissions-Policy", _permissions_policy())
        hsts = settings.hsts_enabled if settings.hsts_enabled is not None else settings.secure_cookies
        if hsts:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


# Path prefix -> requests allowed per 60s window, per client IP.
def _limits() -> list[tuple[str, int]]:
    return [
        ("/api/auth/login", settings.rate_limit_login_per_min),
        ("/api/auth/dev-login", settings.rate_limit_login_per_min),
        ("/api/attendance/scan", settings.rate_limit_scan_per_min),
        ("/api/attendance/event", settings.rate_limit_scan_per_min),
    ]


_WINDOW = 60.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window limiter for a few sensitive POST paths."""

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @staticmethod
    def _client_ip(request: Request) -> str:
        # Cloud Run / proxies put the real client first in X-Forwarded-For.
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _limit_for(self, path: str) -> int | None:
        for prefix, cap in _limits():
            if path.startswith(prefix):
                return cap
        return None

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.method != "POST":
            return await call_next(request)
        cap = self._limit_for(request.url.path)
        if cap is None:
            return await call_next(request)

        key = (request.url.path, self._client_ip(request))
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > _WINDOW:
                q.popleft()
            if len(q) >= cap:
                retry = max(1, int(_WINDOW - (now - q[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — slow down and try again shortly."},
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)
        return await call_next(request)


# Kiosk endpoints identify the employee by scanned QR token, not the session cookie, so CSRF is
# meaningless there — exempt them (they're already gated by KIOSK_KEY when configured).
_CSRF_EXEMPT_PREFIXES = (
    "/api/attendance/scan",
    "/api/attendance/event",
    "/api/attendance/offline-sync",
)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit-token CSRF guard for cookie-authenticated, state-changing requests.

    A non-httponly ``csrf`` cookie is issued on responses; the frontend echoes it back in the
    ``X-CSRF-Token`` header on unsafe requests. Requests without the session cookie (Bearer-token
    API clients, the unauthenticated kiosk) are not cookie-authenticated and are left alone.

    The token cookie is persistent and given the SAME lifetime as the session cookie: a session-
    scoped CSRF cookie would be dropped on browser close while the week-long session cookie survived,
    leaving the pair desynced — and every cookie-authenticated POST (including the login that would
    recover the session) would then 403 until some GET happened to reseed. To be doubly safe against
    any such desync, a failed check still reissues a fresh token so the client self-heals on retry.
    """

    @staticmethod
    def _issue_token(response: Response) -> None:
        response.set_cookie(
            key=settings.csrf_cookie_name, value=secrets.token_urlsafe(32),
            httponly=False, secure=settings.secure_cookies, samesite="lax", path="/",
            max_age=settings.jwt_expire_minutes * 60,
        )

    async def dispatch(self, request: Request, call_next):
        needs_check = (
            settings.csrf_enabled
            and request.method not in _SAFE_METHODS
            and request.cookies.get(settings.cookie_name)          # cookie-authenticated only
            and not request.url.path.startswith(_CSRF_EXEMPT_PREFIXES)
        )
        if needs_check:
            cookie_tok = request.cookies.get(settings.csrf_cookie_name)
            header_tok = request.headers.get(settings.csrf_header_name)
            if not cookie_tok or not header_tok or not hmac.compare_digest(cookie_tok, header_tok):
                rejected = JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
                # Reseed on rejection so a desynced client (e.g. a persistent session cookie whose
                # token cookie was dropped) recovers on the next attempt instead of looping on 403.
                if not cookie_tok:
                    self._issue_token(rejected)
                return rejected

        response: Response = await call_next(request)
        # Issue a token the first time we see a client without one, so the SPA can read + echo it.
        if settings.csrf_enabled and not request.cookies.get(settings.csrf_cookie_name):
            self._issue_token(response)
        return response
