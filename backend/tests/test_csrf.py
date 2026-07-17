"""CSRF double-submit protection for cookie-authenticated, state-changing requests."""
from __future__ import annotations

from app import constants as C
from app.config import settings
from app.security import create_access_token


def test_safe_get_issues_a_csrf_cookie(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert client.cookies.get(settings.csrf_cookie_name)  # server seeded the token


def test_state_change_without_token_is_rejected(client, make_user):
    # Cookie-authenticated (session set) but no CSRF cookie/header -> 403.
    user = make_user(C.ROLE_ACCOUNT_MANAGER)
    client.cookies.set(settings.cookie_name, create_access_token(user.id))
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 403
    assert "csrf" in r.json()["detail"].lower()


def test_rejection_reseeds_token_so_client_self_heals(client, make_user):
    # Persistent session cookie but no CSRF cookie (e.g. the token cookie was dropped on browser
    # close): the request is rejected, but the 403 response issues a fresh token so the retry works.
    user = make_user(C.ROLE_ACCOUNT_MANAGER)
    client.cookies.set(settings.cookie_name, create_access_token(user.id))
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 403
    assert r.cookies.get(settings.csrf_cookie_name)  # reseeded on the rejection itself


def test_state_change_with_mismatched_token_is_rejected(client, make_user):
    user = make_user(C.ROLE_ACCOUNT_MANAGER)
    client.cookies.set(settings.cookie_name, create_access_token(user.id))
    client.cookies.set(settings.csrf_cookie_name, "aaa")
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT},
                      headers={settings.csrf_header_name: "bbb"})
    assert r.status_code == 403


def test_state_change_with_matching_token_passes_csrf(client, make_user, auth):
    # auth() sets a matching cookie+header pair; CSRF passes so we reach the handler (404, no task).
    auth(make_user(C.ROLE_ACCOUNT_MANAGER))
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 404


def test_request_without_session_cookie_skips_csrf(client):
    # No session cookie -> not cookie-authenticated -> CSRF is skipped; auth layer returns 401.
    r = client.patch("/api/tasks/1/priority", json={"priority": C.PRIORITY_URGENT})
    assert r.status_code == 401


def test_kiosk_scan_is_exempt_from_csrf(client, make_user):
    # A logged-in admin's browser carries a session cookie, but kiosk paths are CSRF-exempt.
    user = make_user(C.ROLE_SUPER_ADMIN)
    client.cookies.set(settings.cookie_name, create_access_token(user.id))
    r = client.post("/api/attendance/scan", json={"token": "does-not-exist"})
    # Not a 403 (CSRF); it reaches the handler and 404s on the unknown QR token.
    assert r.status_code == 404
