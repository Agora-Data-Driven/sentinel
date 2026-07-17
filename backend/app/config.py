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

    # --- Auth --------------------------------------------------------------
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # one week
    cookie_name: str = "sentinel_session"
    secure_cookies: bool = False  # set true behind https in prod

    dev_login_enabled: bool = True  # /api/auth/dev-login — pick a seeded user, no OAuth

    # Startup safety net: if the DB has no active Super Admin, this account is (re)created so a
    # login is always possible. Change the password after first sign-in.
    bootstrap_admin_email: str = "melo@agora.ph"
    bootstrap_admin_password: str = "Agora2026!"

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
    # The mastery engine, embedded in the Academy tab. Must be a *.agoradatadriven.com host or the
    # shared session cookie won't reach it inside the iframe.
    skill_mastery_url: str = "https://mastery.agoradatadriven.com"

    # --- Cron / scheduled jobs --------------------------------------------
    # Daily auto-processing endpoint (/api/cron/daily) requires this shared secret in the
    # X-Cron-Key header. Cloud Scheduler sends it. Super Admins can also trigger it while logged in.
    cron_key: str = ""

    # --- Kiosk -------------------------------------------------------------
    # The tablet kiosk is a trusted device: attendance punches are identified by the scanned QR
    # token, not by a logged-in user. In prod, lock these routes to the LAN / a device key.
    kiosk_key: str = ""  # if set, kiosk endpoints require ?kiosk_key= or X-Kiosk-Key header


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
