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


def _ensure_columns() -> None:
    """Add columns create_all() won't add to an already-existing table (zero-setup SQLite dev DBs).

    create_all only creates MISSING tables, never alters existing ones, so a new model column would
    be invisible on a DB seeded before it existed. This adds any such column idempotently. Prod uses
    Alembic; this is a safety net so a local demo DB never 500s on `no such column`.
    """
    from sqlalchemy import inspect, text

    from .database import engine
    added = [
        ("tasks", "maintasks_json", "TEXT DEFAULT '[]'"),
        ("tasks", "service_charge", "VARCHAR(32)"),  # optional internal-only charge
        ("tasks", "created_by_id", "INTEGER"),  # automatic creator tag (drives own-task visibility)
        # Service-template defaults auto-filled onto new tasks (added after the table shipped).
        ("service_templates", "default_priority", "VARCHAR(16)"),
        ("service_templates", "default_labels_json", "TEXT DEFAULT '[]'"),
        ("service_templates", "default_description", "TEXT"),
        # Shift templates: reusable schedules assignable to a team or an employee.
        ("teams", "shift_template_id", "INTEGER"),
        ("users", "shift_template_id", "INTEGER"),
        # Offline-punch idempotency key.
        ("attendance_events", "client_uid", "VARCHAR(64)"),
        # The four growth dimensions (was missing from this list when e5a7c3d9b1f4 shipped —
        # a pre-2026-07-26 local DB 500'd with `no such column: dimension`).
        ("professional_goals", "dimension", "VARCHAR(16) DEFAULT 'professional'"),
        # The growth journal became per-dimension (2026-08-01), so each of the four tabs holds its
        # own titled entries instead of one shared list plus a free-form blob. Existing rows
        # backfill to 'spiritual' — where the whole journal rendered before the split — so nothing
        # appears to jump tabs on upgrade.
        # 🔴 Prod deploys don't run alembic, so THIS LIST is the only path this column takes to
        # production. The alembic revision beside it is for local/migrated DBs.
        ("growth_items", "dimension", "VARCHAR(16) DEFAULT 'spiritual'"),
        # The Atrium projection (2026-08-03). `atrium_task_id` is the card this row projects onto —
        # before it existed, `atrium_visible` was a flag that referred to nothing and every "shared"
        # task pointed at a card that was never created. `atrium_sync_error` holds the last failed
        # push so a stale client card is LOUD instead of silent. Both nullable, so existing rows
        # read as "never published / nothing failed", which is exactly right.
        # 🔴 Same rule as the growth column above: this list is the path these take to production.
        ("tasks", "atrium_task_id", "VARCHAR(64)"),
        ("tasks", "atrium_sync_error", "TEXT"),
        # Atrium owns the CLIENT list now (2026-08-05, `services/client_sync`); a client it stops
        # listing is DEACTIVATED here rather than deleted, because deleting nulls `Task.client_id` on
        # every past task and blanks that client's history. `BOOLEAN DEFAULT true` — existing rows
        # must stay visible, and never `DEFAULT 1`: this ALTER also runs against prod POSTGRES, which
        # rejects an integer default on a boolean.
        # 🔴 Same rule as the columns above: this list is the path it takes to production.
        ("clients", "is_active", "BOOLEAN DEFAULT true"),
        # The status key/label split (2026-08-03, decision D13). `name` is a LABEL and may be
        # renamed; `vocab_key` is the stable identity and `stage` is the Atrium stage a status
        # projects onto. Without these, `STAGE_BY_STATUS` was keyed by the display string and a
        # rename in Manage silently broke the bridge for every client card.
        # (Column is `vocab_key`, not `key` — see the model: bare `key` is a dialect keyword.)
        ("task_vocab", "vocab_key", "VARCHAR(40)"),
        ("task_vocab", "stage", "VARCHAR(24)"),
        # The workflow fields (2026-08-03, Stage 2 / M2–M5): when work starts, when it really
        # finished, whether it is filed, whether it is parked (and where it came from), and where
        # its review stands. Alembic e8b3f5c7a2d9 is the local/migrated path; 🔴 THIS LIST is the
        # one that reaches production.
        # `BOOLEAN DEFAULT false`, never `DEFAULT 0`: this ALTER also runs against prod POSTGRES,
        # which rejects an integer default on a boolean column. SQLite accepts `false` too.
        ("tasks", "start_date", "DATE"),
        ("tasks", "completed_at", "TIMESTAMP"),
        ("tasks", "archived", "BOOLEAN DEFAULT false"),
        ("tasks", "on_hold", "BOOLEAN DEFAULT false"),
        ("tasks", "hold_reason", "TEXT"),
        ("tasks", "resume_to", "VARCHAR(32)"),
        ("tasks", "review_state", "VARCHAR(20)"),
        ("tasks", "reviewer_id", "INTEGER"),
        # The reverse channel (D4 / WP 3.5). `client_changes_open` counts the CLIENT's open change
        # requests — separate from `review_state`, which is the internal approval gate (D5): a
        # client must never be able to satisfy or block a team lead's sign-off.
        # DEFAULT 0, not NULL: the board renders the pill on `> 0`, and a NULL comparison is
        # neither true nor false in SQL.
        ("tasks", "client_changes_open", "INTEGER DEFAULT 0"),
        ("task_comments", "client_author", "VARCHAR(160)"),
        # WP 3.4 — which adoption run created the row. What makes importing live client cards
        # reversible; NULL for everything a human raised.
        ("tasks", "adoption_batch", "VARCHAR(40)"),
    ]
    try:
        insp = inspect(engine)
        for table, column, decl in added:
            if table not in insp.get_table_names():
                continue
            if column not in {c["name"] for c in insp.get_columns(table)}:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {decl}"))
                print(f"[sentinel] migrated: added {table}.{column}")
        # Data fix (2026-07-27): the 'mental' growth dimension became 'philosophical'. Alembic
        # f9b4d7a2c5e8 carries the same UPDATE for migrated DBs; this idempotent pass covers
        # create_all-only DBs (and prod, where deploys don't run alembic automatically) — an
        # un-migrated 'mental' goal would silently render under Professional (dimOf fallback).
        if "professional_goals" in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("UPDATE professional_goals SET dimension='philosophical' WHERE dimension='mental'"))
        # Backstop for the growth-journal split: ADD COLUMN ... DEFAULT backfills existing rows on
        # both SQLite and Postgres 11+, but a row written through an older path (or a DB where the
        # column arrived without the default) would be left NULL — and a NULL dimension renders in
        # no tab at all, which looks exactly like the entry was deleted.
        if "growth_items" in insp.get_table_names():
            with engine.begin() as conn:
                conn.execute(text("UPDATE growth_items SET dimension='spiritual' WHERE dimension IS NULL OR dimension=''"))
    except Exception as exc:  # never let a migration attempt crash startup
        print(f"[sentinel] column ensure skipped: {exc}")


def _backfill_status_meta() -> None:
    """Give every existing status its key + stage on boot (decision D13).

    🔴 This is how the two new task_vocab columns reach PRODUCTION for rows that already exist —
    the same reason `retire_statuses` runs every boot. Without it a live board would hold statuses
    with no stage and the bridge would fall back to the legacy label-keyed map for every card.
    """
    from .database import SessionLocal
    from .services import task_config

    db = SessionLocal()
    try:
        fixed = task_config.backfill_status_meta(db)
        if fixed:
            print(f"[sentinel] status meta backfilled ({fixed} field(s))")
        # 🔴 STRICTLY AFTER the backfill, and that ordering is the whole reason this lives here
        # rather than in `_seed_config`. `rename_statuses` finds its row by KEY (D13 — the label is
        # the one facet that moves, so it cannot also be the handle), and on a board seeded before
        # `task_vocab.key` existed the key is filled in by the call directly above. Run it first and
        # it matches nothing, silently, on exactly the old boards that need it most.
        for line in task_config.rename_statuses(db):
            print(f"[sentinel] renamed task status: {line}")
    except Exception as exc:            # never let a backfill crash startup
        print(f"[sentinel] status meta backfill skipped: {exc}")
    finally:
        db.close()


def _seed_config() -> None:
    """One-time: populate the editable config tables from the code defaults so a fresh (or
    pre-feature) DB keeps today's statuses/labels/priorities + service recipes, now editable in the
    Manage page. Idempotent — only seeds a table that is empty."""
    from sqlalchemy import func, select

    from .database import SessionLocal
    from .models import ServiceTemplate, ShiftTemplate, TaskVocabItem
    from .services import task_config, task_templates

    db = SessionLocal()
    try:
        if not db.execute(select(func.count(ShiftTemplate.id))).scalar():
            # Starter shift templates — fully editable in Manage afterwards.
            for name, start, end, brk in [
                ("Day (8AM–5PM)", "08:00", "17:00", 60),
                ("Afternoon (1PM–10PM)", "13:00", "22:00", 60),
                ("Part-time PM (6PM–10PM)", "18:00", "22:00", 0),
            ]:
                db.add(ShiftTemplate(name=name, start=start, end=end, break_min=brk))
            db.commit()
            print("[sentinel] seeded shift templates")
        if not db.execute(select(func.count(TaskVocabItem.id))).scalar():
            # name -> (stable key, Atrium stage) for the shipped statuses (task_config.STATUS_SEED
            # is the one definition; backfill_status_meta heals existing boards with the same map).
            status_meta = {n: (k, st) for n, k, st in task_config.STATUS_SEED}
            for kind, items in task_config.SEED.items():
                for i, (name, color) in enumerate(items):
                    # Statuses carry their stable key + Atrium stage from the moment they are
                    # seeded (D13); labels/priorities have neither concept.
                    meta = status_meta.get(name, (None, None)) if kind == "status" else (None, None)
                    db.add(TaskVocabItem(kind=kind, name=name, color=color, sort_order=i,
                                         key=meta[0], stage=meta[1]))
            db.commit()
            print("[sentinel] seeded task vocab (statuses/labels/priorities)")
        if not db.execute(select(func.count(ServiceTemplate.id))).scalar():
            for row in task_templates.seed_rows():
                db.add(ServiceTemplate(**row))
            db.commit()
            print("[sentinel] seeded service templates")
        # 🔴 Also NOT an "only if empty" seed (WP 5.3). A service added to SEED_TEMPLATES has to
        # reach boards that already have services — which is all of them — or it exists only in
        # code and has to be retyped in Manage per environment. Insert-only, matched by key, so a
        # board's own edits and deliberate deletions are never reverted.
        new_services = task_templates.sync_seed(db)
        if new_services:
            print(f"[sentinel] added shipped service templates: {', '.join(new_services)}")
        # 🔴 Labels are DERIVED from the department (D14), so unlike everything above this is NOT
        # an "only if the table is empty" seed — it must run on EVERY boot. The boards that carry
        # the retired Design/Copy/Ads/SEO/Dev vocabulary are precisely the non-empty ones, and a
        # deploy is the only moment we get to heal them. Idempotent and silent when there is
        # nothing to do.
        changed = task_config.reconcile_labels(db)
        if any(changed.values()):
            print(f"[sentinel] reconciled labels from departments: {changed}")
        # A status removed from the code defaults still has a seeded DB row overriding them, so it
        # keeps its board column until that row goes. Idempotent; this is what lands the change in
        # prod, where deploys don't run Alembic. See task_config.RETIRED_STATUSES.
        for line in task_config.retire_statuses(db):
            print(f"[sentinel] retired task status: {line}")
    except Exception as exc:  # never let seeding crash startup
        print(f"[sentinel] config seed skipped: {exc}")
    finally:
        db.close()


def _ensure_default_shift() -> None:
    """Guarantee exactly one company-default Shift Template exists.

    The shift model has a single source of truth — the Shift Templates catalog — with one template
    flagged ``is_default`` as the base every shift resolves from. The Alembic migration establishes it
    in prod; this is the belt-and-suspenders for a fresh ``create_all`` DB (local dev) or any DB that
    somehow ended up with zero defaults. Idempotent; a no-op once a default exists.
    """
    from sqlalchemy import select

    from .database import SessionLocal
    from .models import ShiftTemplate

    db = SessionLocal()
    try:
        if db.execute(select(ShiftTemplate).where(ShiftTemplate.is_default.is_(True))).scalars().first():
            return
        first = db.execute(select(ShiftTemplate).order_by(ShiftTemplate.id)).scalars().first()
        if first:
            first.is_default = True
            db.commit()
            print(f"[sentinel] flagged default shift template: {first.name}")
    except Exception as exc:  # never let this crash startup
        print(f"[sentinel] default shift ensure skipped: {exc}")
    finally:
        db.close()


def _mirror_clients() -> None:
    """Pull Atrium's client registry on boot (Atrium owns clients; Sentinel owns staff).

    🔴 **Runs LAST and can never stop the boot.** It reaches over the network to another service, so
    every failure mode — bridge unconfigured, Atrium cold-starting, a timeout, a shape we don't
    understand — is logged and swallowed. `client_sync.sync` already refuses to act on an empty or
    failed answer (deactivation is driven by absence, so "no answer" must never be read as "no
    clients"); this handler is the second belt: a client list that is one boot stale is a nuisance,
    a Sentinel that will not start is an outage.
    """
    from .database import SessionLocal
    from .services import client_sync

    db = SessionLocal()
    try:
        report = client_sync.sync(db)
        if report["ok"]:
            print(f"[sentinel] client mirror: +{report['created']} new, "
                  f"{report['linked']} linked, {report['deactivated']} deactivated")
        else:
            print(f"[sentinel] client mirror skipped: {report['error']}")
    except Exception as exc:                                   # noqa: BLE001 — see the docstring
        print(f"[sentinel] client mirror failed: {exc}")
    finally:
        db.close()


@app.on_event("startup")
def _startup() -> None:
    # Create tables if missing (SQLite zero-setup). Prod uses Alembic migrations.
    create_all()
    _ensure_columns()
    _seed_config()
    _backfill_status_meta()
    _ensure_default_shift()
    _startup_safeguards()
    _mirror_clients()


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
    # NB: "/dashboard" is NOT here — it needs the board-deep-link forward, so it has its own route
    # below (`dashboard_page`). Adding it back here would shadow that and break every
    # `/dashboard?open=<id>` notification minted between 2026-07-26 and 2026-08-03.
    "/attendance": "attendance.html",
    "/approvals": "approvals.html",
    "/gym": "gym.html",
    "/growth": "growth.html",
    "/reading": "reading.html",
    "/academy": "academy.html",
    # The two reading-program tabs — each hosts a Mastery Engine iframe pinned to its
    # program (?program=philosophy / ?program=spiritual). Paths are new; no redirects needed.
    "/philosophical": "philosophical.html",
    "/spiritual": "spiritual.html",
    "/people": "people.html",
    "/leave": "leave.html",
    "/north-star": "north-star.html",
    "/reports": "reports.html",
    "/settings": "settings.html",
    "/manage": "manage.html",
    "/payroll": "payroll.html",
    # The Task Board got its own page back on 2026-08-03 (decision D7). It was embedded in the
    # dashboard from 2026-07-26 until then; `/dashboard?open=<id>` still forwards here, see below.
    "/tasks": "tasks.html",
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


# Board deep-link params. A notification/palette link carrying one of these means "open the board",
# and the board lives at /tasks again — so /dashboard has to hand them over.
_BOARD_PARAMS = ("open", "new", "view")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page(request: Request):
    """The dashboard — but a BOARD deep-link is forwarded to /tasks, query string intact.

    🔴 The board moved out of the dashboard on 2026-08-03 (decision D7), and it was embedded here
    from 2026-07-26 until then. Every task notification minted in that window is a row in
    `notifications` reading `/dashboard?open=<id>`, and those rows are permanent — so this route must
    forward them forever, exactly as `/tasks` forwarded the other way for the four months before it.

    It forwards ONLY when a board param is present. `/dashboard` on its own is the landing page for
    everyone, every day; redirecting it wholesale would send the whole company to the task board.
    """
    if any(p in request.query_params for p in _BOARD_PARAMS):
        q = request.url.query
        return RedirectResponse(url="/tasks" + (f"?{q}" if q else ""))
    return _page("dashboard.html")
