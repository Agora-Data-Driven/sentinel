"""Logging + error tracking setup.

Two layers, both zero-config-friendly:

1. **Structured logging** — on Cloud Run, anything written to stdout as JSON with a ``severity``
   field is ingested by Cloud Logging and, for ERROR+ with a traceback, surfaced in Error
   Reporting automatically. No SDK or DSN needed. Locally we log plain, readable lines instead.

2. **Sentry (optional)** — if ``SENTRY_DSN`` is set *and* ``sentry-sdk`` is installed, wire it up.
   Absent either, this is a no-op — nothing to install for the default deployment.

Call ``configure_observability()`` once at startup, and install ``log_unhandled_exceptions`` so
uncaught errors are logged with a traceback (which is what Error Reporting keys on).
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings

# Cloud Logging severities: DEBUG/INFO/WARNING/ERROR/CRITICAL map 1:1 to Python level names.
_LOG = logging.getLogger("sentinel")


class _JsonFormatter(logging.Formatter):
    """Render each record as a single-line JSON object Cloud Logging understands."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.now(timezone.utc).isoformat(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, default=str)


def configure_observability() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    # JSON in production (Cloud Logging parses it); human-readable locally.
    if settings.is_production:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    _LOG.setLevel(level)

    _init_sentry()


def _init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        _LOG.warning("SENTRY_DSN is set but sentry-sdk is not installed — skipping Sentry init.")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
    )
    _LOG.info("Sentry error tracking enabled.")


class ExceptionLoggingMiddleware(BaseHTTPMiddleware):
    """Log any unhandled exception with a full traceback, then return a clean 500.

    The traceback on stderr/stdout is what Cloud Error Reporting groups; without this, an uncaught
    error would surface only as a bare 500 with no diagnostic trail.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            _LOG.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def get_logger(name: str = "sentinel") -> logging.Logger:
    return logging.getLogger(name)
