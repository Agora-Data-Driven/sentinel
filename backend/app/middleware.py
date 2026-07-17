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
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "manifest-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", _CSP)
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Kiosk needs the camera on its own origin; nothing else is granted.
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
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
    """

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
                return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})

        response: Response = await call_next(request)
        # Issue a token the first time we see a client without one, so the SPA can read + echo it.
        if settings.csrf_enabled and not request.cookies.get(settings.csrf_cookie_name):
            response.set_cookie(
                key=settings.csrf_cookie_name, value=secrets.token_urlsafe(32),
                httponly=False, secure=settings.secure_cookies, samesite="lax", path="/",
            )
        return response
