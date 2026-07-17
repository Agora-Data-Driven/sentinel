"""Observability: logging config + the unhandled-exception middleware."""
from __future__ import annotations

import logging

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app.observability import ExceptionLoggingMiddleware, configure_observability


def test_configure_observability_sets_root_handler():
    configure_observability()
    root = logging.getLogger()
    assert root.handlers, "root logger should have a handler"


def test_configure_observability_without_sentry_is_noop():
    # No SENTRY_DSN in the test env -> must not raise.
    configure_observability()


def test_unhandled_exception_becomes_clean_500_and_is_logged(caplog):
    async def boom(request):
        raise RuntimeError("kaboom")

    app = Starlette(routes=[Route("/boom", boom)])
    app.add_middleware(ExceptionLoggingMiddleware)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="sentinel"):
        r = client.get("/boom")

    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error"}
    # The traceback was logged (this is what Cloud Error Reporting groups on).
    assert any("Unhandled error" in rec.message for rec in caplog.records)
