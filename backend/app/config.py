"""Central runtime configuration for Sentinel.

Everything is driven by environment variables (see ``.env.example``). Sensible defaults keep local
dev zero-setup: SQLite on disk, a throwaway dev secret, and DEV_LOGIN enabled so you can pick a
seeded user without wiring up Google OAuth.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---------------------------------------------------------------
    app_name: str = "Sentinel"
    org_name: str = "Agora"
    environment: str = "development"
    timezone: str = "Asia/Manila"  # store UTC, display + apply rules in PH time

    # --- Database ----------------------------------------------------------
    # SQLite locally (zero-setup); point DATABASE_URL at Postgres in prod.
    database_url: str = "sqlite:///./sentinel.db"
    # Postgres connection pool (ignored on SQLite). See database.py for why the default was wrong.
    #
    # 🔴 The ceiling is CLOUD SQL's `max_connections`, NOT the threadpool. `db-f1-micro` allows only
    # ~25 connections for the whole estate — shared with the seed job, migrations and any psql — so
    # `pool_size` is what one warm instance HOLDS AT REST and has to stay small. `max_overflow` is
    # burst capacity that is opened on demand and closed on return, so it costs nothing at idle.
    # Worst case is `(pool_size + max_overflow) x max-instances` (deploy.ps1), which is why those two
    # numbers must be changed together — 20+20 across 10 instances would ask for 400.
    #
    # 5 + 15 is sized to the work, not to the thread count: a board request now holds its connection
    # for ~60ms rather than the multiple seconds it did before `CardPrefetch`, so 20 concurrent
    # checkouts is several hundred requests/second per instance. If a genuinely slow endpoint appears
    # (a big CSV export, an adoption run over a large workspace), raise these — and `max_connections`
    # or the instance tier with them.
    db_pool_size: int = 5
    db_max_overflow: int = 15
    # Fail fast instead of hanging: a caller who cannot get a connection in 10s is better served by
    # an error it can retry than by a request that eventually times out at the load balancer.
    db_pool_timeout: int = 10

    # --- Auth --------------------------------------------------------------
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # one week
    cookie_name: str = "sentinel_session"
    secure_cookies: bool = False  # set true behind https in prod

    dev_login_enabled: bool = True  # /api/auth/dev-login — pick a seeded user, no OAuth
    # Dev-login is a PASSWORDLESS "become any user" door — fine locally, dangerous in prod.
    # It is forced OFF when environment == "production" unless this escape hatch is set true.
    allow_dev_login_in_prod: bool = False

    # --- Live reload (local development only) -------------------------------
    # `GET /api/dev/reload` — an SSE stream that fires when anything under frontend/ changes, so a
    # saved CSS/JS edit reaches the browser without a manual refresh (routers/dev.py).
    #
    # 🔴 Defaults to True and is nonetheless UNREACHABLE in production, by TWO independent gates —
    # see `dev_reload_active` below and the localhost test in `frontend/static/js/app.js`. Defaulting
    # it on is what makes local dev zero-config, which is the whole point; defaulting it off would
    # mean every dev has to discover a flag before the feature exists for them.
    #
    # There is deliberately NO `allow_dev_reload_in_prod` escape hatch (unlike dev-login above). The
    # endpoint walks the frontend directory on a timer and holds a connection open per browser tab —
    # on Cloud Run that is pointless work against an immutable container image, and a reload watcher
    # is never the answer to a production question.
    dev_reload: bool = True

    # Startup safety net: if the DB has no active Super Admin, this account is (re)created so a
    # login is always possible. Change the password after first sign-in.
    bootstrap_admin_email: str = "melo@agora.ph"
    bootstrap_admin_password: str = "Agora2026!"

    # The Agora ecosystem's owner — the same super admin that runs the portal. Ensured as an active
    # Sentinel Super Admin on every boot (idempotent, SSO-only, no password) so signing in through
    # the portal always lands them here. SSO itself never creates accounts, so without this the
    # owner would be locked out of their own Sentinel until someone added them by hand. Comma-
    # separated for more than one; blank to disable.
    platform_admin_emails: str = "info@agoradatadriven.com"

    # Google OAuth 2.0 (optional; DEV_LOGIN is the fallback when unset)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # --- Central portal SSO (the Agora portal is the one front door) --------
    # The HMAC key the portal signs `ag_sso` with (Secret Manager `platform-sso-key`). Unset =
    # SSO is inert and the existing login paths are unchanged, so a default/local run is unaffected.
    # NOTE: the cookie is scoped to `.agoradatadriven.com`, so it only ever reaches Sentinel on its
    # custom domain — on a raw *.run.app host SSO is silently inert (fail-safe, by design).
    platform_sso_secret: str = ""
    # Where /login sends people (the portal). Unset = Sentinel keeps its own login form.
    portal_login_url: str = ""
    # The portal's origin for the ATRIUM TASK BRIDGE (services/atrium_tasks.py). Atrium owns the
    # client-facing tasks; the internal board reads them over HMAC so a task typed into a client's
    # Atrium shows up here. Unset = derived from portal_login_url; if neither resolves, the bridge
    # is simply off and the board shows Sentinel's own rows only.
    atrium_api_url: str = ""
    # How long a fetched Atrium BOARD LIST may be reused (seconds; 0 disables the cache).
    #
    # 🔴 This is a LATENCY control, not a tuning knob to leave at 0. `atrium_tasks.fetch_tasks` is a
    # blocking cross-service HTTP call on the critical path of every board load, every Monitor load
    # and every Coach digest, and `atrium_bridge` pools no connections — so without this, Atrium's
    # latency (up to the 10s read timeout) is added straight onto Sentinel's. Only successful reads
    # are cached and every write invalidates, so the worst case is a client card up to this many
    # seconds stale on the board. Raising it much past ~60s would start being visible to a person
    # editing in Atrium and refreshing here.
    atrium_cache_seconds: int = 15

    # --- AI task drafting (services/ai_draft.py, 2026-09-02) ----------------------------------------
    # Vertex AI Gemini through the Cloud Run runtime service account — GCP-billed, NO API key — the
    # same pattern Atrium's intel_ai.py uses. Off unless VERTEX_GEMINI_ENABLED=1 AND VERTEX_PROJECT is
    # set; off means the Draft-with-AI button says so and the AM files the tasks by hand. The runtime
    # SA needs roles/aiplatform.user or every call answers 403 (deploy.ps1 grants it).
    vertex_gemini_enabled: bool = False
    vertex_project: str = ""
    vertex_location: str = "global"
    vertex_model: str = "gemini-2.5-flash"
    # Per-task work sessions (services/task_sessions.py). A session that runs past the cap is clamped
    # and flagged rather than trusted — nobody works eight hours on one card without a break, and a
    # forgotten timer must not inflate a day.
    session_cap_minutes: int = 240
    # How long a resolved role->capability matrix is cached IN-PROCESS (`services/permissions`).
    # `require_cap` runs on every guarded request, so resolving from the DB each time would put a
    # SELECT on a large share of all traffic. The cost is that a REVOKE made on one instance is not
    # seen by the other two until their cache expires — hence a short window rather than "until
    # boot". `0` disables caching entirely and resolves per request, which is the right setting if
    # permissions ever become something that has to be revoked in an emergency.
    permissions_cache_seconds: int = 15
    # OPTIONAL: pin the Growth hub's Mentor Library to ONE Atrium workspace's Watcher archive
    # (services/atrium_watcher.py). Unset (the default) reads EVERY workspace, which is what you
    # want: Watcher's channels are per-client, but mentor content (Nick Saraev, Carson Reed, ...)
    # isn't any one client's -- it lives wherever the team happened to add it.
    # 🔴 This defaulted to "agora", a workspace that has never existed, so the picker was
    # permanently empty. Do NOT re-pin it to a guessed key; "" is the working default.
    atrium_watcher_client_key: str = ""
    # The host Sentinel should be reached on. The shared cookie is scoped to
    # .agoradatadriven.com, so on the raw *.run.app URL (an old bookmark, a stale link) SSO simply
    # cannot work and you get asked to sign in again for no visible reason. Set this and browsers
    # hitting the run.app host are sent to the real one. Unset = no redirect (safe default).
    canonical_host: str = ""
    # The mastery engine, embedded in the Academy tab. Must be a *.agoradatadriven.com host or the
    # shared session cookie won't reach it inside the iframe.
    skill_mastery_url: str = "https://mastery.agoradatadriven.com"

    # --- Cron / scheduled jobs --------------------------------------------
    # Daily auto-processing endpoint (/api/cron/daily) requires this shared secret in the
    # X-Cron-Key header. Cloud Scheduler sends it. Super Admins can also trigger it while logged in.
    cron_key: str = ""

    # --- Personal context report (services/personal_report + report_doc) ----
    # The Google Doc the daily personal report is published into, and whose report it is.
    # 🔴 The document is REPLACED WHOLESALE on every run — point this only at a file dedicated to
    # it, never one anyone edits by hand. It must be shared with this service's runtime service
    # account as an Editor: the doc lives in a personal @gmail.com Drive, and domain-wide
    # delegation cannot reach a consumer account, so sharing is the only way in.
    # Both blank (the default) = the feature is off and the daily pass skips it entirely.
    report_doc_id: str = ""
    report_user_email: str = ""
    # 🔴 Required on Cloud Run. The metadata server hands the runtime service account a
    # `cloud-platform` token, which the Drive API REFUSES — it wants the Drive scope specifically,
    # and a metadata token cannot be widened to it. Naming the runtime account here makes
    # services/report_doc.py exchange that token for a Drive-scoped one via the IAM Credentials API
    # (the account impersonates itself, so it needs `roles/iam.serviceAccountTokenCreator` on
    # itself). Leave blank locally, where ADC is a user credential and impersonation is not the
    # right shape. Symptom if it is wrongly blank in prod: a 403/404 that looks exactly like the
    # document never having been shared.
    report_impersonate_sa: str = ""

    # --- Kiosk -------------------------------------------------------------
    # The tablet kiosk is a trusted device: attendance punches are identified by the scanned QR
    # token, not by a logged-in user. In prod, lock these routes to the LAN / a device key.
    kiosk_key: str = ""  # if set, kiosk endpoints require ?kiosk_key= or X-Kiosk-Key header

    # --- Security headers / rate limiting ----------------------------------
    # In-memory per-IP rate limiting for sensitive endpoints (login brute-force, QR-token
    # guessing). Per-instance on Cloud Run — a basic abuse brake, not a distributed quota.
    rate_limit_enabled: bool = True
    # /api/auth/login + /dev-login, per IP per minute.
    # 🔴 PER IP, AND THE OFFICE IS ONE IP. Behind NAT this is a whole-team budget, not a per-person
    # one: at the old value of 10, a Monday morning of everyone signing in at once — with the ordinary
    # share of typos and retries — could spend it in seconds and answer real staff "Too many
    # requests", which reads as being locked out. 30 is still a hard brake on scripted guessing
    # (passwords are PBKDF2-SHA256 at 200k iterations, so an attacker gets ~43k attempts a day
    # against a single address), and the limiter is per-process anyway (see middleware.py).
    rate_limit_login_per_min: int = 30
    rate_limit_scan_per_min: int = 120   # /api/attendance/scan + /event, per IP (busy kiosk-friendly)
    # Send HSTS only when actually behind HTTPS. Defaults to follow secure_cookies.
    hsts_enabled: bool | None = None
    # Who may frame Sentinel pages (CSP `frame-ancestors`). Sentinel embeds its own same-origin
    # pages (North Star's who-we-are.html) and is itself meant to live inside the Agora portal, so
    # the default allows 'self' plus the agoradatadriven.com ecosystem. Set to "'none'" to forbid
    # all framing, or tighten to specific hosts. Note: `*.agoradatadriven.com` does NOT cover the
    # bare apex, so both are listed.
    csp_frame_ancestors: str = "'self' https://*.agoradatadriven.com https://agoradatadriven.com"

    # --- Observability ----------------------------------------------------
    log_level: str = "INFO"  # DEBUG|INFO|WARNING|ERROR
    # Optional Sentry error tracking. Empty = off (Cloud Logging / Error Reporting still work from
    # structured stdout logs). Requires `sentry-sdk` installed to take effect.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # --- CSRF (double-submit token) ---------------------------------------
    # Only enforced for cookie-authenticated, state-changing requests. Bearer-token API clients and
    # the QR-token kiosk endpoints are exempt (they don't rely on the ambient session cookie).
    csrf_enabled: bool = True
    csrf_cookie_name: str = "sentinel_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    # --- Derived --------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def dev_login_active(self) -> bool:
        """Effective dev-login switch. Off in production unless explicitly allowed."""
        if self.is_production and not self.allow_dev_login_in_prod:
            return False
        return self.dev_login_enabled

    @property
    def dev_reload_active(self) -> bool:
        """Effective live-reload switch. Hard OFF in production, with no escape hatch.

        Deliberately stricter than `dev_login_active`: that one has `allow_dev_login_in_prod`
        because there are real (if rare) reasons to impersonate a user on a staging deploy. There is
        no such reason to watch the filesystem of an immutable container image, so production is not
        a configuration here — it is the end of the question.
        """
        return self.dev_reload and not self.is_production

    @property
    def jwt_secret_is_default(self) -> bool:
        return self.jwt_secret == "dev-only-change-me-in-production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
