"""Sentinel FastAPI application — REST API + static frontend server.

Run locally:  uvicorn app.main:app --reload   (from the backend/ directory)
Seed first:   python seed.py
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import settings
from .database import create_all, get_db
from .security import create_access_token, user_from_sso
from .middleware import CSRFMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .observability import ExceptionLoggingMiddleware, configure_observability, get_logger
from .routers import (
    admin,
    attendance,
    auth,
    cron,
    development,
    gym,
    internal,
    leave,
    manage,
    meta,
    notifications,
    payroll,
    people,
    reports,
    stream,
    tasks,
)

# sentinel/backend/app/main.py -> parents[2] == sentinel/
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
PAGES_DIR = FRONTEND_DIR / "pages"

# Structured logging + optional Sentry, configured at import so startup logs are formatted too.
configure_observability()
log = get_logger()

app = FastAPI(
    title="Sentinel API",
    version="1.0.0",
    description="Internal operations command center for Agora — attendance, gym, tasks, people, leave.",
)

# Hardening middleware. The last-added runs outermost, so SecurityHeaders wraps everything and
# decorates every response — including the 403/429s produced by the guards it wraps.
# Effective order (outer -> inner): SecurityHeaders -> RateLimit -> CSRF -> ExceptionLogging -> app.
# ExceptionLogging is innermost so a route's 500 is caught, logged with a traceback, and still
# flows back out through the header/CSRF middleware.
app.add_middleware(ExceptionLoggingMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def _canonical_host_redirect(request, call_next):
    """Send browsers from the raw run.app URL to the real hostname.

    The portal's `ag_sso` cookie is scoped to `.agoradatadriven.com`, so on `*.run.app` it is never
    sent: single sign-on silently can't work and the visitor is asked to log in again with no
    explanation. An old bookmark is enough to hit this. Redirecting closes that trap for good.

    Deliberately narrow, so this can't take the service down:
      - only GET, and only real browser navigations (Accept: text/html) -- APIs and probes untouched;
      - only when CANONICAL_HOST is configured AND we're being served from a different host;
      - the run.app URL still answers everything else, so it stays a working fallback.
    """
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    canonical = (settings.canonical_host or "").strip().lower()
    if (
        canonical
        and host
        and host != canonical
        and host.endswith(".run.app")
        and request.method == "GET"
        and "text/html" in (request.headers.get("accept") or "")
    ):
        target = f"https://{canonical}{request.url.path}"
        if request.url.query:
            target += f"?{request.url.query}"
        return RedirectResponse(url=target, status_code=307)
    return await call_next(request)


@app.on_event("startup")
def _startup() -> None:
    # Create tables if missing (SQLite zero-setup). Prod uses Alembic migrations.
    create_all()
    _startup_safeguards()


@app.on_event("startup")
async def _bind_event_broker() -> None:
    # Capture the running loop so sync request handlers can publish SSE events across threads.
    import asyncio

    from .events import broker
    broker.bind_loop(asyncio.get_running_loop())


def _production_security_warnings() -> None:
    """Loudly flag insecure prod config at boot. Warn-only so a misconfig never causes lockout."""
    if not settings.is_production:
        return
    checks = [
        (settings.jwt_secret_is_default,
         "JWT_SECRET is the built-in dev default - anyone can forge sessions. "
         "Set a strong JWT_SECRET secret and redeploy."),
        (settings.dev_login_active,
         "passwordless DEV_LOGIN is ACTIVE (ALLOW_DEV_LOGIN_IN_PROD=true) - anyone can sign in as "
         "any user. Wire Google OAuth / password login, then remove the override."),
        (not settings.secure_cookies,
         "SECURE_COOKIES is false - session cookies will be sent over plain HTTP. "
         "Set SECURE_COOKIES=true behind HTTPS."),
        (settings.bootstrap_admin_password == "Agora2026!",
         "bootstrap admin is using the default password - sign in and change it now."),
    ]
    for triggered, message in checks:
        if triggered:
            print(f"[sentinel] SECURITY (production): {message}")


def _startup_safeguards() -> None:
    """Log which database we're on, and guarantee a login is always possible.

    If the DB ever has no active Super Admin (empty/wiped DB, bad state), recreate the bootstrap
    admin so no one is ever locked out. On a normal boot this is just a fast count query.
    """
    from sqlalchemy import func, select

    from .constants import ROLE_SUPER_ADMIN
    from .database import SessionLocal
    from .models import User
    from .utils.passwords import hash_password

    backend = (
        "PostgreSQL" if settings.database_url.startswith("postgres")
        else "SQLite" if settings.database_url.startswith("sqlite") else "other"
    )
    print(f"[sentinel] startup: db={backend} env={settings.environment}")
    if settings.environment == "production" and backend == "SQLite":
        print("[sentinel] WARNING: production is running on EPHEMERAL SQLite — DATABASE_URL is not set! "
              "Data will not persist. Set the DATABASE_URL secret.")
    _production_security_warnings()

    db = SessionLocal()
    try:
        active_admins = db.execute(
            select(func.count(User.id)).where(
                User.role == ROLE_SUPER_ADMIN, User.is_active.is_(True)
            )
        ).scalar() or 0
        if active_admins == 0:
            email = settings.bootstrap_admin_email.strip().lower()
            existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if existing:
                existing.role = ROLE_SUPER_ADMIN
                existing.is_active = True
                if not existing.password_hash:
                    existing.password_hash = hash_password(settings.bootstrap_admin_password)
            else:
                db.add(User(
                    name="Sentinel Admin", email=email, role=ROLE_SUPER_ADMIN, is_active=True,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                ))
            db.commit()
            print(f"[sentinel] no active Super Admin found — ensured bootstrap admin: {email}")

        # Ensure the ecosystem owner(s) are always an active Super Admin. They sign in through the
        # portal (SSO), which never creates accounts, so without this the owner is locked out of
        # their own Sentinel with the "you're signed in to the portal but not a Sentinel user"
        # message. Idempotent: create if missing, elevate/reactivate if present; no password needed
        # (login is via SSO — password_hash stays null).
        for raw in settings.platform_admin_emails.split(","):
            owner = raw.strip().lower()
            if not owner:
                continue
            u = db.execute(select(User).where(User.email == owner)).scalar_one_or_none()
            if u:
                if u.role != ROLE_SUPER_ADMIN or not u.is_active:
                    u.role = ROLE_SUPER_ADMIN
                    u.is_active = True
                    db.commit()
                    print(f"[sentinel] elevated platform owner to active Super Admin: {owner}")
            else:
                db.add(User(name="Agora Admin", email=owner, role=ROLE_SUPER_ADMIN, is_active=True))
                db.commit()
                print(f"[sentinel] created platform owner as Super Admin (SSO-only): {owner}")
    except Exception as exc:  # never let a safeguard crash startup
        print(f"[sentinel] startup safeguard skipped: {exc}")
    finally:
        db.close()


# --- API routers -----------------------------------------------------------
for r in (auth, attendance, gym, tasks, people, leave, notifications, reports, admin, meta, manage, payroll, cron, stream, internal, development):
    app.include_router(r.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "app": settings.app_name, "env": settings.environment}


# --- Static assets ---------------------------------------------------------
# check_dir=False so the API can boot even before the frontend assets are built.
(FRONTEND_DIR / "static").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static"), check_dir=False), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(str(PAGES_DIR / name))


# PWA files must be served from the root scope.
@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(str(FRONTEND_DIR / "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(str(FRONTEND_DIR / "sw.js"), media_type="application/javascript")


# --- Page routes (client-side auth: each page calls /api/auth/me) ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/login", include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)):
    """Serve the login screen — but skip it entirely for anyone already signed in to Agora.

    If the visitor arrives with a valid portal `ag_sso` cookie AND is an active Sentinel user, we
    drop them straight on the dashboard instead of showing a login form they don't need (no second
    sign-in, no login-page flash). We mint the normal Sentinel session on the way so the app behaves
    exactly like a password login afterwards (logout works, no per-request HMAC). Everyone else --
    no portal session, or a portal email that isn't a Sentinel user -- still gets the login page,
    where login.js handles the portal bounce / "not a Sentinel user" message.
    """
    user = user_from_sso(request, db)
    if user:
        resp = RedirectResponse(url="/dashboard", status_code=302)
        resp.set_cookie(
            key=settings.cookie_name, value=create_access_token(user.id), httponly=True,
            secure=settings.secure_cookies, samesite="lax",
            max_age=settings.jwt_expire_minutes * 60, path="/",
        )
        return resp
    return _page("login.html")


_PAGES = {
    "/dashboard": "dashboard.html",
    "/attendance": "attendance.html",
    "/gym": "gym.html",
    "/growth": "growth.html",
    "/reading": "reading.html",
    "/tasks": "tasks.html",
    "/academy": "academy.html",
    "/people": "people.html",
    "/leave": "leave.html",
    "/north-star": "north-star.html",
    "/reports": "reports.html",
    "/settings": "settings.html",
    "/manage": "manage.html",
    "/payroll": "payroll.html",
    "/kiosk": "kiosk.html",
    "/scanner": "scanner.html",
}

for _route, _file in _PAGES.items():
    app.add_api_route(
        _route,
        (lambda f=_file: (lambda: _page(f)))(),
        methods=["GET"],
        include_in_schema=False,
    )
