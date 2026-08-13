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
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

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
        # Static assets and page shells carry Last-Modified but (before this) no Cache-Control,
        # so browsers applied HEURISTIC freshness and could serve a stale JS/CSS copy after a
        # deploy without ever revalidating — the service worker's "network-first" fetch() is
        # satisfied by the HTTP cache, so it can't help. Seen live 2026-07-27: day-old
        # dashboard.js ran against the new /api/dashboard and rendered "undefined" KPIs.
        # "no-cache" keeps the copy but forces ETag revalidation on every use: a cheap 304
        # when unchanged, the new file the moment a deploy changes it. /api/* is left alone
        # (JSON responses carry no validators, so heuristic caching never applied there).
        if not request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-cache")
        return response


# 🔴 THE SSE STREAMS MUST NEVER BE COMPRESSED. This is the whole reason there is a wrapper here
# instead of a bare `app.add_middleware(GZipMiddleware)`.
#
# Starlette's `GZipResponder` handles a streaming response by writing each chunk into a `GzipFile`
# and sending whatever lands in the buffer. gzip's deflate stage BUFFERS — a 40-byte SSE frame
# produces zero output bytes — so the browser's EventSource would receive nothing until enough
# events had accumulated to fill a block. That is precisely the "streaming arrives as one blob"
# failure in AGENTS.md §4, except no header can fix it: the bytes genuinely have not been emitted.
# It would break the live board (`/api/stream`) and local live-reload (`/api/dev/reload`) in a way
# that looks like "events are slow" rather than like a compression bug.
#
# The exclusion is by PATH, deliberately, not by sniffing the response content-type. By the time a
# `text/event-stream` content-type is visible we are already inside the responder and committed to
# its send-wrapper; a path prefix is decided before any of that, and it is the same fact stated
# where a reader will look for it.
_NO_COMPRESS_PREFIXES = (
    "/api/stream",      # routers/stream.py — the live board + notification push
    "/api/dev/reload",  # routers/dev.py — local live reload (404s in production, harmless here)
)


class ConditionalGZipMiddleware:
    """GZip every response EXCEPT the Server-Sent Events streams.

    Sentinel serves a vanilla-JS frontend with no build step (AGENTS.md §8), so the page shells load
    real source files: `/tasks` alone pulls `app.js` (65 kb) + `taskboard.js` (215 kb) +
    `styles.css` (83 kb), and the board's own JSON response is comment-and-prose heavy. None of it
    was compressed. Text compresses ~70-80%, and Cloud Run bills internet egress by the byte, so
    this is faster AND cheaper.

    Pure ASGI on purpose — `BaseHTTPMiddleware` (what the other three middlewares here use) would add
    another task-group-plus-memory-stream layer around every response, which is overhead in the exact
    place we are trying to remove it.
    """

    def __init__(self, app: ASGIApp, minimum_size: int = 500, compresslevel: int = 6) -> None:
        self.app = app
        # 🔴 compresslevel 6, not Starlette's default of 9. Level 9 costs materially more CPU for
        # ~1-2% smaller output, and this runs on a shared-core instance where CPU is the scarce
        # thing — spending it to save a byte we are not paying for is the wrong trade.
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith(_NO_COMPRESS_PREFIXES):
            await self.app(scope, receive, send)
            return
        await self._gzip(scope, receive, send)


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
    # The login page's own <form> (POST /login, the no-JS fallback in main.py). A native form post
    # cannot send an X-CSRF-Token header, and the page is a static file with no way to render a token
    # into it — so that route does its own Origin/Referer check instead (`main._is_same_origin`).
    # Without this exemption a STALE session cookie would make the check fire and 403 the one path
    # that exists to recover from a broken session.
    "/login",
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
                # Reseed on EVERY rejection so a desynced client (e.g. a persistent session cookie
                # whose token cookie was dropped, or a stale token left by an earlier deploy)
                # recovers on the next attempt instead of looping on 403. This used to reseed only
                # when the cookie was ABSENT, which left the mismatch case — a cookie present but not
                # matching the header — permanently stuck, the one shape a client cannot fix itself.
                # Handing a fresh token to a genuine cross-site attacker costs nothing: they cannot
                # read the cookie back to echo it.
                self._issue_token(rejected)
                return rejected

        response: Response = await call_next(request)
        # Issue a token the first time we see a client without one, so the SPA can read + echo it.
        if settings.csrf_enabled and not request.cookies.get(settings.csrf_cookie_name):
            self._issue_token(response)
        return response
