"""The sign-in path a PHONE actually takes (2026-09-05), and the estate cookie Sentinel now re-mints.

The report was "login on mobile isn't smooth — Sentinel and Agora seem to have different logins".
Traced end to end, a cold visit to sentinel.agoradatadriven.com/tasks did this:

    /tasks  -> whole dashboard shell downloaded + run -> /api/auth/me 401 -> /login (a form nobody
    should use) -> /api/auth/config -> POST /api/auth/sso 401 -> portal/login (a SECOND form) ->
    tap Google -> back to /login -> /dashboard   (the /tasks deep link lost on the way)

Now: `/tasks` -> 302 `/login?next=/tasks` -> 302 straight into the portal's Google flow -> back to
`/login?next=/tasks` -> session minted -> `/tasks`. Nothing is drawn before the Google picker.

The second half: `ag_sso` lives 12h and only the PORTAL re-minted it, but staff live here on a 7-day
session and never visit the portal — so the Mastery Engine frames inside Sentinel (Coach included)
drew their own login form ~12h after every sign-in. `/api/auth/me` now hands the cookie back.

Most cases here are about what must NOT happen: the guard that stops the bounce from looping, the
`?next=` that must never become an open redirect, and a live portal cookie that is never overwritten.
"""
from __future__ import annotations

from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app import sso
from app.config import settings
from app.routers import auth as auth_router

SECRET = "shared-platform-sso-key-for-tests"
PORTAL = "https://portal.agoradatadriven.com/login"
CANONICAL = {"host": "sentinel.agoradatadriven.com"}   # where the parent-domain cookie can reach us


@pytest.fixture
def sso_wired(monkeypatch):
    monkeypatch.setattr(settings, "platform_sso_secret", SECRET)
    monkeypatch.setattr(settings, "portal_login_url", PORTAL)


def _get(client, path, **kw):
    return client.get(path, follow_redirects=False, **kw)


def _set_cookies(resp, name):
    """Every Set-Cookie for `name` on the response, parsed (the TestClient jar drops foreign domains)."""
    out = []
    for raw in resp.headers.get_list("set-cookie"):
        jar = SimpleCookie()
        jar.load(raw)
        if name in jar:
            out.append(jar[name])
    return out


# --- 1. A cold visit never downloads a page it cannot use ---------------------------------------

def test_a_page_with_no_credential_goes_to_login_with_the_deep_link(client):
    r = _get(client, "/tasks?open=12")
    assert r.status_code == 302
    assert r.headers["location"] == "/login?next=%2Ftasks%3Fopen%3D12"


def test_the_dashboard_is_guarded_too(client):
    assert _get(client, "/dashboard").headers["location"] == "/login?next=%2Fdashboard"


def test_a_board_deep_link_on_the_dashboard_still_forwards_first(client):
    """The /dashboard?open= forward is permanent (notification rows); the guard must not shadow it."""
    r = _get(client, "/dashboard?open=7")
    assert r.status_code in (302, 307) and r.headers["location"] == "/tasks?open=7"


def test_the_kiosk_is_served_with_no_credential(client):
    """It must boot offline from the service-worker cache on a tablet that may hold no cookie at all."""
    assert _get(client, "/kiosk").status_code == 200


def test_a_present_but_dead_cookie_still_gets_the_shell(client):
    """Presence only: validity stays `/api/auth/me`'s job, and the page's own redirect handles it."""
    client.cookies.set(settings.cookie_name, "not-a-valid-jwt")
    assert _get(client, "/tasks").status_code == 200


# --- 2. /login with a portal cookie: straight through, to where you were going -------------------

def test_a_portal_cookie_signs_you_in_and_keeps_the_deep_link(client, make_user, sso_wired):
    make_user(email="ana@agora.ph")
    client.cookies.set(sso.COOKIE_NAME, sso.mint(SECRET, "ana@agora.ph"))
    r = _get(client, "/login?next=%2Ftasks%3Fopen%3D12")
    assert r.status_code == 302 and r.headers["location"] == "/tasks?open=12"
    assert r.cookies.get(settings.cookie_name)
    assert not _set_cookies(r, auth_router.BOUNCE_COOKIE)
    assert client.get("/api/auth/me").json()["email"] == "ana@agora.ph"


@pytest.mark.parametrize("bad", ["//evil.example.com/x", "https://evil.example.com", "/\\evil.example.com",
                                 "/login", "/login?next=/tasks", "tasks", ""])
def test_next_is_never_an_open_redirect(client, make_user, sso_wired, bad):
    make_user(email="ana@agora.ph")
    client.cookies.set(sso.COOKIE_NAME, sso.mint(SECRET, "ana@agora.ph"))
    r = _get(client, "/login", params={"next": bad})
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"


# --- 3. /login with NO cookie, where SSO works: the server bounces before drawing anything -------

def test_no_cookie_on_the_canonical_host_bounces_to_the_portals_google_flow(client, sso_wired):
    r = _get(client, "/login?next=%2Ftasks%3Fopen%3D12", headers=CANONICAL)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(PORTAL + "?")
    q = parse_qs(urlsplit(loc).query)
    assert q["prefer"] == ["google"]
    # `next` targets OUR /login (the only route that mints a Sentinel session), on the canonical
    # host, still carrying the page the visitor was opening.
    assert q["next"] == ["https://sentinel.agoradatadriven.com/login?next=%2Ftasks%3Fopen%3D12"]
    # ...and the one-bounce guard is armed, JS-readable, for a few seconds only.
    (guard,) = _set_cookies(r, auth_router.BOUNCE_COOKIE)
    assert int(guard["max-age"]) == auth_router.BOUNCE_WINDOW_SECONDS and not guard["httponly"]


def test_a_dashboard_bound_bounce_carries_no_redundant_next(client, sso_wired):
    loc = _get(client, "/login", headers=CANONICAL).headers["location"]
    assert parse_qs(urlsplit(loc).query)["next"] == ["https://sentinel.agoradatadriven.com/login"]


def test_a_bounce_that_follows_a_bounce_shows_the_form_instead(client, sso_wired):
    """The loop-breaker: the portal sent us back with nothing; bouncing again is the 2026-08-11 loop."""
    client.cookies.set(auth_router.BOUNCE_COOKIE, "1757000000")
    r = _get(client, "/login", headers=CANONICAL)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


@pytest.mark.parametrize("path", ["/login?local=1", "/login?error=google", "/login?error=noaccount"])
def test_the_escape_hatches_still_render_the_form(client, sso_wired, path):
    assert _get(client, path, headers=CANONICAL).status_code == 200


def test_off_the_canonical_host_there_is_no_bounce(client, sso_wired):
    """On *.run.app (or localhost) the browser never sends `ag_sso`; a bounce there would loop."""
    assert _get(client, "/login").status_code == 200


def test_unwired_sso_never_bounces(client):
    assert _get(client, "/login", headers=CANONICAL).status_code == 200


def test_a_cookie_that_is_present_but_useless_is_left_to_login_js(client, sso_wired):
    """It may be a valid portal login that is not a Sentinel user — bouncing that loops forever, and
    only `POST /api/auth/sso` (403 vs 401) can say which. So the server renders and lets JS decide."""
    client.cookies.set(sso.COOKIE_NAME, "garbage.garbage")
    assert _get(client, "/login", headers=CANONICAL).status_code == 200


# --- 4. /api/auth/me hands a signed-in person the estate cookie back --------------------------------

def _me(client, headers=CANONICAL):
    return client.get("/api/auth/me", headers=headers)


def test_me_re_mints_ag_sso_for_a_session_that_has_lost_it(client, make_user, auth, sso_wired):
    user = make_user(email="ana@agora.ph")
    auth(user)
    r = _me(client)
    assert r.status_code == 200
    (c,) = _set_cookies(r, sso.COOKIE_NAME)
    assert c["domain"] == sso.COOKIE_DOMAIN and c["secure"] and c["httponly"]
    assert c["samesite"].lower() == "none" and int(c["max-age"]) == sso.DEFAULT_TTL_SECONDS
    payload = sso.verify(SECRET, c.value)          # it must verify with the shared secret...
    assert payload and payload["sub"] == "ana@agora.ph"
    assert payload["clients"] == []                 # ...and grant an employee no client dashboards


def test_the_owner_seat_gets_the_portals_own_answer(client, make_user, auth, sso_wired):
    auth(make_user("super_admin", email="info@agoradatadriven.com"))
    (c,) = _set_cookies(_me(client), sso.COOKIE_NAME)
    assert sso.verify(SECRET, c.value)["clients"] == ["*"]


def test_a_live_portal_cookie_is_never_replaced(client, make_user, auth, sso_wired):
    """The portal knows a person's client grants; we do not. Ours only ever fills a gap."""
    user = make_user(email="ana@agora.ph")
    auth(user)
    client.cookies.set(sso.COOKIE_NAME, sso.mint(SECRET, "ana@agora.ph", clients=("acme",)))
    assert not _set_cookies(_me(client), sso.COOKIE_NAME)


def test_a_dead_portal_cookie_is_replaced(client, make_user, auth, sso_wired):
    user = make_user(email="ana@agora.ph")
    auth(user)
    client.cookies.set(sso.COOKIE_NAME, sso.mint(SECRET, "ana@agora.ph", ttl_seconds=-1))
    assert len(_set_cookies(_me(client), sso.COOKIE_NAME)) == 1


def test_no_mint_off_the_canonical_host_or_without_the_secret(client, make_user, auth, sso_wired, monkeypatch):
    user = make_user(email="ana@agora.ph")
    auth(user)
    assert not _set_cookies(_me(client, headers=None), sso.COOKIE_NAME)   # testserver: cookie can't be set
    monkeypatch.setattr(settings, "platform_sso_secret", "")
    assert not _set_cookies(_me(client), sso.COOKIE_NAME)


def test_no_mint_while_acting_as_someone_else(client, make_user, auth, sso_wired):
    """The estate cookie is IDENTITY; it must never name the target of an act-as."""
    real = make_user("super_admin", email="info@agoradatadriven.com")
    target = make_user(email="ana@agora.ph")
    auth(real)
    client.cookies.set(settings.act_as_cookie_name, str(target.id))
    r = _me(client)
    assert r.json()["email"] == "ana@agora.ph" and r.json()["acting_as"]
    assert not _set_cookies(r, sso.COOKIE_NAME)


# --- 5. The pieces the browser side depends on ---------------------------------------------------

def test_the_service_worker_cache_was_bumped_with_the_scripts():
    """login.js and app.js changed; a stale sw.js would keep serving the old bounce. (§5 rule.)"""
    from app.main import FRONTEND_DIR
    sw = (FRONTEND_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const CACHE = "sentinel-v116"' not in sw


def test_login_js_reads_the_servers_bounce_marker():
    from app.main import FRONTEND_DIR
    js = (FRONTEND_DIR / "static" / "js" / "login.js").read_text(encoding="utf-8")
    assert auth_router.BOUNCE_COOKIE in js and "prefer=google" in js
