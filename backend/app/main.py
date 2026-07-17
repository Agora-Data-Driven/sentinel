"""Sentinel FastAPI application — REST API + static frontend server.

Run locally:  uvicorn app.main:app --reload   (from the backend/ directory)
Seed first:   python seed.py
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import create_all
from .middleware import CSRFMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware
from .routers import (
    admin,
    attendance,
    auth,
    cron,
    gym,
    leave,
    manage,
    meta,
    notifications,
    payroll,
    people,
    reports,
    tasks,
)

# sentinel/backend/app/main.py -> parents[2] == sentinel/
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
PAGES_DIR = FRONTEND_DIR / "pages"

app = FastAPI(
    title="Sentinel API",
    version="1.0.0",
    description="Internal operations command center for Agora — attendance, gym, tasks, people, leave.",
)

# Hardening middleware. The last-added runs outermost, so SecurityHeaders wraps everything and
# decorates every response — including the 403/429s produced by the guards it wraps.
# Effective order (outer -> inner): SecurityHeaders -> RateLimit -> CSRF -> app.
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.on_event("startup")
def _startup() -> None:
    # Create tables if missing (SQLite zero-setup). Prod uses Alembic migrations.
    create_all()
    _startup_safeguards()


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
    except Exception as exc:  # never let a safeguard crash startup
        print(f"[sentinel] startup safeguard skipped: {exc}")
    finally:
        db.close()


# --- API routers -----------------------------------------------------------
for r in (auth, attendance, gym, tasks, people, leave, notifications, reports, admin, meta, manage, payroll, cron):
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


_PAGES = {
    "/login": "login.html",
    "/dashboard": "dashboard.html",
    "/attendance": "attendance.html",
    "/gym": "gym.html",
    "/tasks": "tasks.html",
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
