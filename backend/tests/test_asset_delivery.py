"""Guards on how CSS/JS reach the browser (2026-08-13).

Two changes with one goal — stop paying for the same 365 kb of frontend on every navigation:

1. **Compression** (`middleware.ConditionalGZipMiddleware`) — nothing was compressed at all, and the
   frontend has no build step, so the shells load real source files.
2. **Content-versioned URLs** (`assets.py`) — `Cache-Control: no-cache` made the browser revalidate
   every asset on every use. A hashed URL is `immutable`, so it is not requested at all.

Both are the kind of work that rots silently: nothing FAILS when a future change quietly drops the
`Vary` header, compresses the SSE stream, or serves an unhashed URL as immutable — it just gets slow
again, or breaks in a way nobody connects to this. Hence these.
"""
from __future__ import annotations

import gzip

import pytest

from app.assets import Assets
from app.config import settings
from app.main import ASSETS
from app.middleware import ConditionalGZipMiddleware


# --- 1. compression -----------------------------------------------------------------------------

def test_a_large_static_asset_is_gzipped_and_arrives_intact(client):
    """🔴 Note there is no `Content-Length` to check: `FileResponse` is a STREAMING response, so
    Starlette takes its chunked-gzip branch and the length is genuinely unknown up front. What
    matters at this level is that the encoding is negotiated and the bytes survive it — the
    compression RATIO is measured in the test below, where the raw output is visible."""
    from app.main import FRONTEND_DIR

    r = client.get("/static/js/app.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    # httpx decodes transparently, so this is the round-tripped file — it must equal the original.
    on_disk = (FRONTEND_DIR / "static" / "js" / "app.js").read_bytes()
    assert r.content == on_disk
    assert len(on_disk) > 20_000, "expected the actual app.js, not an error page"


def test_compression_meaningfully_shrinks_the_frontend():
    """The point of the exercise, measured on the real file. `/tasks` ships ~356 kb of source JS+CSS
    because the frontend has no build step (AGENTS.md §8); gzip takes that to ~110 kb."""
    from app.main import FRONTEND_DIR

    source = (FRONTEND_DIR / "static" / "js" / "taskboard.js").read_bytes()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/javascript")]})
        await send({"type": "http.response.body", "body": source})

    sent = _drive(ConditionalGZipMiddleware(app), "/static/js/taskboard.js", accept_gzip=True)
    compressed = int(_header(sent, b"content-length"))
    assert compressed < len(source) * 0.4, (
        f"taskboard.js only compressed to {compressed / len(source):.0%} of source")
    # And it really is gzip, not a mislabelled passthrough.
    assert gzip.decompress(b"".join(m.get("body", b"") for m in sent
                                    if m["type"] == "http.response.body")) == source


def test_the_vary_header_is_set_so_caches_do_not_mix_encodings(client):
    """Without `Vary: Accept-Encoding` a shared cache can hand a gzipped body to a client that did
    not ask for one. Starlette sets it; this pins that we still go through the path that does."""
    r = client.get("/static/js/app.js", headers={"Accept-Encoding": "gzip"})
    assert "accept-encoding" in r.headers.get("vary", "").lower()


def test_a_client_that_does_not_accept_gzip_gets_plain_bytes(client):
    r = client.get("/static/js/app.js", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers


def test_api_json_is_compressed_too(client):
    """The board's own payload is the biggest JSON in the app and the reason this is not
    static-only."""
    big = {"rows": [{"title": f"Task {i}", "note": "x" * 200} for i in range(200)]}

    async def app(scope, receive, send):
        import json
        body = json.dumps(big).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    sent = _drive(ConditionalGZipMiddleware(app), "/api/tasks", accept_gzip=True)
    assert _header(sent, b"content-encoding") == b"gzip"


# --- 2. the SSE streams are never compressed ----------------------------------------------------
#
# 🔴 Driven through the ASGI interface directly, NOT through TestClient — exactly as
# `test_dev_reload.py` does, and for the same reason: `client.stream()` against a live SSE endpoint
# never sees `is_disconnected()` become True under TestClient's portal and hangs the suite forever.

def _drive(app, path: str, *, accept_gzip: bool) -> list[dict]:
    """Run one ASGI request through `app`, returning every message it sent."""
    import asyncio

    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "scheme": "http", "server": ("test", 80), "client": ("test", 1234),
        "headers": [(b"accept-encoding", b"gzip")] if accept_gzip else [],
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _header(sent: list[dict], name: bytes) -> bytes | None:
    for message in sent:
        if message["type"] == "http.response.start":
            for key, value in message["headers"]:
                if key.lower() == name:
                    return value
    return None


async def _sse_app(scope, receive, send):
    """A stand-in for `routers/stream.py`: small frames, sent one at a time, forever-ish."""
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/event-stream")]})
    for i in range(3):
        await send({"type": "http.response.body",
                    "body": f"event: task\ndata: {{\"id\": {i}}}\n\n".encode(),
                    "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


@pytest.mark.parametrize("path", ["/api/stream", "/api/dev/reload"])
def test_the_sse_streams_are_not_compressed(path):
    """🔴 THE guard. gzip's deflate stage buffers, so a 40-byte SSE frame produces zero output bytes
    and the browser's EventSource receives NOTHING until enough events accumulate to fill a block —
    the live board would silently stop being live. No header fixes that; the bytes really have not
    been emitted. See `_NO_COMPRESS_PREFIXES`."""
    sent = _drive(ConditionalGZipMiddleware(_sse_app), path, accept_gzip=True)
    assert _header(sent, b"content-encoding") is None, f"{path} was compressed"

    # And every frame arrived intact, in its own message — which is what "live" means here.
    bodies = [m["body"] for m in sent if m["type"] == "http.response.body" and m["body"]]
    assert bodies == [b'event: task\ndata: {"id": 0}\n\n',
                      b'event: task\ndata: {"id": 1}\n\n',
                      b'event: task\ndata: {"id": 2}\n\n']


def test_a_normal_path_with_the_same_payload_IS_compressed():
    """The control for the test above: the exclusion must be about the PATH, not about streaming
    responses in general — otherwise it would prove nothing."""
    sent = _drive(ConditionalGZipMiddleware(_sse_app), "/api/tasks", accept_gzip=True)
    assert _header(sent, b"content-encoding") == b"gzip"


# --- 3. content-versioned asset URLs ------------------------------------------------------------


def _shell(client, path):
    """A page shell, as a SIGNED-IN browser fetches it.

    Since 2026-09-05 a visitor carrying no credential at all is redirected to `/login?next=` before
    the shell is served (`main._guarded_page`, presence-only) — so these tests carry a cookie. Its
    validity is irrelevant here; the shell never checks it, `/api/auth/me` does.
    """
    client.cookies.set(settings.cookie_name, "any-value-presence-is-all-the-shell-checks")
    return client.get(path)


def test_page_shells_hand_out_versioned_css_and_js(client):
    r = _shell(client, "/tasks")
    assert r.status_code == 200
    html = r.text
    for asset in ("/static/js/app.js", "/static/js/taskboard.js", "/static/css/styles.css"):
        assert f'{asset}?v={ASSETS.build_id}"' in html, f"{asset} was not versioned"


def test_the_shell_itself_still_revalidates(client):
    """🔴 The scheme rests on this. The document that HANDS OUT immutable URLs must never itself be
    cached, or a deploy's new URLs would never reach the browser."""
    r = _shell(client, "/tasks")
    assert r.headers["cache-control"] == "no-cache"


def test_a_versioned_asset_is_immutable(client):
    r = client.get(f"/static/js/app.js?v={ASSETS.build_id}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_an_unversioned_asset_keeps_todays_behaviour(client):
    """The service worker's precache list, old bookmarks and anything we did not rewrite must be
    completely unaffected — `no-cache`, exactly as before."""
    r = client.get("/static/js/app.js")
    assert r.headers["cache-control"] == "no-cache"


def test_a_STALE_version_is_not_immutable(client):
    """🔴 A browser holding a pre-deploy page will ask for the old `?v=`. The file on disk is now the
    NEW one, so answering `immutable` would pin today's bytes under yesterday's name for a year."""
    r = client.get("/static/js/app.js?v=deadbeef1234")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


# --- 4. the build id itself ---------------------------------------------------------------------

def _frontend(tmp_path, *, css: str = "body{color:red}", js: str = "console.log(1)"):
    static = tmp_path / "static"
    (static / "css").mkdir(parents=True)
    (static / "js").mkdir(parents=True)
    (static / "css" / "styles.css").write_text(css)
    (static / "js" / "app.js").write_text(js)
    (tmp_path / "pages").mkdir()
    return tmp_path


def test_the_build_id_follows_CONTENT_not_timestamps(tmp_path):
    """🔴 Property 1 in `assets.py`. A git checkout re-stamps every mtime, so an mtime-keyed id would
    change on every deploy and throw away caches that were still valid. Same bytes, same id."""
    a = Assets(_frontend(tmp_path / "one"))
    b = Assets(_frontend(tmp_path / "two"))
    assert a.build_id == b.build_id

    changed = Assets(_frontend(tmp_path / "three", css="body{color:blue}"))
    assert changed.build_id != a.build_id


def test_a_renamed_file_is_a_new_build_id(tmp_path):
    root = _frontend(tmp_path / "named")
    before = Assets(root).build_id
    (root / "static" / "js" / "app.js").rename(root / "static" / "js" / "main.js")
    assert Assets(root).build_id != before


def test_a_missing_static_directory_does_not_raise(tmp_path):
    """A frontend that failed to copy is a broken deploy — it must not be a container that cannot
    boot at all, which is the same call `check_dir=False` makes on the mount."""
    (tmp_path / "pages").mkdir()
    assert Assets(tmp_path).build_id


# --- 5. the rewrite ------------------------------------------------------------------------------

def test_the_rewrite_skips_a_url_that_already_has_a_query(tmp_path):
    """🔴 `logo.png?v=21` is hand-versioned in every shell. Appending a second `?v=` would produce a
    URL that 404s — silently breaking one asset to speed up the rest is not a trade worth making."""
    assets = Assets(_frontend(tmp_path))
    out = assets.rewrite(b'<img src="/static/img/logo.png?v=21">')
    assert out == b'<img src="/static/img/logo.png?v=21">'


def test_only_css_and_js_are_rewritten(tmp_path):
    assets = Assets(_frontend(tmp_path))
    out = assets.rewrite(b'<link href="/static/favicon.png"><script src="/static/js/app.js">')
    assert b'/static/favicon.png"' in out
    assert f'/static/js/app.js?v={assets.build_id}"'.encode() in out


def test_external_urls_are_untouched(tmp_path):
    """The shells load Google Fonts by absolute URL; the regex is anchored on `/static/` so it can
    never reach them."""
    assets = Assets(_frontend(tmp_path))
    src = b'<link href="https://fonts.googleapis.com/css2?family=Inter">'
    assert assets.rewrite(src) == src
