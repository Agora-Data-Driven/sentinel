"""The login page's floor: `POST /login` (no JavaScript) + what a failed login is allowed to SAY.

Both exist because of the same class of report — "I'm on the login page and I cannot get in, and
nothing tells me why":

* the form was JS-only, with no `action` and no `name=` on its inputs, so a login.js that failed to
  load left "Sign in" wired to nothing: the click silently re-GET'd /login with the fields cleared.
  The page rendered perfectly and could not admit anyone, with no error on screen and no failed
  request in the logs;
* every failure answered "Invalid email or password", including the accounts that have **no
  password at all** (SSO-only, which is what the platform-owner bootstrap and an admin who leaves
  the password field blank both create). Those people retried until the rate limiter stopped them.

The weighting here is deliberate: most cases are about REFUSALS and about the two doors never
disagreeing, because a second way in is only safe while it accepts exactly what the first one does.
"""
from __future__ import annotations

from app.config import settings
from app.main import FRONTEND_DIR
from app.utils.passwords import hash_password

ORIGIN = "http://testserver"          # what TestClient's own Host header makes same-origin
NO_PASSWORD_HINT = "no password yet"
GENERIC = "Invalid email or password"


def _post(client, email, password, **kw):
    return client.post("/login", data={"email": email, "password": password},
                       follow_redirects=False, **kw)


def test_the_form_posts_somewhere_real_without_js():
    """The fallback IS the markup — if these attributes go, the dead form comes back.

    Asserted on the file rather than on a route because that is where the regression happened: the
    route can be perfect and the page still unusable when the form has nothing to submit to.
    """
    html = (FRONTEND_DIR / "pages" / "login.html").read_text(encoding="utf-8")
    assert 'method="post"' in html and 'action="/login"' in html
    assert 'name="email"' in html and 'name="password"' in html


def test_form_login_signs_you_in(client, make_user):
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    r = _post(client, "ana@agora.ph", "s3cret", headers={"origin": ORIGIN})
    # 303 so the browser re-issues as GET: a refresh must never re-post the password.
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert r.cookies.get(settings.cookie_name)


def test_the_session_it_mints_actually_works(client, make_user):
    """A cookie that doesn't authenticate is the same failure wearing a success code."""
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    _post(client, "ana@agora.ph", "s3cret", headers={"origin": ORIGIN})
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "ana@agora.ph"


def test_a_wrong_password_is_refused_in_readable_html(client, make_user):
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    r = _post(client, "ana@agora.ph", "wrong", headers={"origin": ORIGIN})
    assert r.status_code == 401
    # HTML, not JSON: the whole point is that this reader has no working JavaScript.
    assert "text/html" in r.headers["content-type"]
    assert GENERIC in r.text
    assert not r.cookies.get(settings.cookie_name)


def test_an_unknown_email_is_refused(client):
    assert _post(client, "nobody@agora.ph", "x", headers={"origin": ORIGIN}).status_code == 401


def test_a_deactivated_account_is_refused_and_stays_generic(client, make_user):
    """Deactivation is security-relevant, so it does NOT get its own message."""
    make_user(email="gone@agora.ph", active=False, password_hash=hash_password("s3cret"))
    r = _post(client, "gone@agora.ph", "s3cret", headers={"origin": ORIGIN})
    assert r.status_code == 401
    assert GENERIC in r.text and NO_PASSWORD_HINT not in r.text


def test_an_sso_only_account_is_told_it_has_no_password(client, make_user):
    """The one case where "wrong password" is a lie — there is no password to get wrong."""
    make_user(email="info@agoradatadriven.com")          # password_hash stays NULL, as SSO users are
    r = _post(client, "info@agoradatadriven.com", "anything", headers={"origin": ORIGIN})
    assert r.status_code == 401
    assert NO_PASSWORD_HINT in r.text
    assert "portal" in r.text.lower()                    # and it says where to go instead


def test_the_api_says_the_same_thing(client, make_user):
    """One definition of failure, or the two doors teach people different things."""
    make_user(email="info@agoradatadriven.com")
    r = client.post("/api/auth/login", json={"email": "info@agoradatadriven.com", "password": "x"})
    assert r.status_code == 401 and NO_PASSWORD_HINT in r.json()["detail"]


def test_the_api_keeps_a_wrong_password_generic(client, make_user):
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    r = client.post("/api/auth/login", json={"email": "ana@agora.ph", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == GENERIC


def test_a_cross_site_post_is_refused(client, make_user):
    """The CSRF defence for this route: the page is a static file and the CSP forbids inline script,
    so there is nowhere to put a double-submit token. A present-and-foreign Origin is refused."""
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    r = _post(client, "ana@agora.ph", "s3cret", headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
    assert not r.cookies.get(settings.cookie_name)


def test_a_foreign_referer_is_refused_too(client, make_user):
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    r = _post(client, "ana@agora.ph", "s3cret",
              headers={"referer": "https://evil.example.com/page"})
    assert r.status_code == 403


def test_no_origin_header_still_works(client, make_user):
    """Fails OPEN on purpose: this route exists for degraded conditions, and refusing a login because
    a client omitted an optional header would break the fallback exactly when it is needed."""
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    assert _post(client, "ana@agora.ph", "s3cret").status_code == 303


def test_a_stale_session_cookie_does_not_block_the_recovery(client, make_user):
    """The shape that made this unrecoverable: arriving at /login WITH a dead session cookie.

    A native form post cannot send X-CSRF-Token, and the CSRF guard fires on any unsafe request that
    carries the session cookie — so without the `/login` exemption the one path that recovers a
    broken session was 403'd by the broken session itself.
    """
    make_user(email="ana@agora.ph", password_hash=hash_password("s3cret"))
    client.cookies.set(settings.cookie_name, "not-a-valid-jwt")
    r = _post(client, "ana@agora.ph", "s3cret", headers={"origin": ORIGIN})
    assert r.status_code == 303


def test_the_csrf_exemption_is_only_that_one_path(client, make_user, db):
    """...and it must not have widened: every OTHER cookie-authenticated write still needs the token."""
    from app.security import create_access_token
    user = make_user(email="ana@agora.ph")
    client.cookies.set(settings.cookie_name, create_access_token(user.id))
    assert client.post("/api/auth/logout").status_code == 403      # no X-CSRF-Token header
