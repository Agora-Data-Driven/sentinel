"""Live reload (`/api/dev/reload`) — weighted toward the gates that keep it out of production.

The feature itself is a convenience; the thing worth pinning is that it CANNOT be reached from a
production deploy. There is no `allow_dev_reload_in_prod` escape hatch, so a test that fails here
means a dev-only filesystem watcher just became reachable in prod, not that a nicety broke.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import HTTPException

from app.config import settings
from app.main import app
from app.routers import dev as dev_router


class _OneShotRequest:
    """A Request stand-in that reports itself disconnected after `alive` polls.

    🔴 The stream is driven directly rather than through TestClient, and that is not a shortcut.
    `reload_stream` loops until `request.is_disconnected()` — which never becomes True under
    TestClient, because its portal keeps the connection open — so `client.stream()` on the 200 path
    hangs the suite forever instead of failing. (Learned the hard way: the first version of this file
    had to be killed.) Anything that needs the 200 path drives the generator with this.
    """

    def __init__(self, alive: int = 1):
        self._polls = 0
        self._alive = alive

    async def is_disconnected(self) -> bool:
        self._polls += 1
        return self._polls > self._alive


def _drive(request=None) -> tuple[dict, list[str]]:
    """Run the endpoint to completion against a self-disconnecting request.

    Returns `(response headers, the SSE chunks it emitted)`.
    """
    async def run():
        resp = await dev_router.reload_stream(request or _OneShotRequest())
        chunks = [c if isinstance(c, str) else c.decode() async for c in resp.body_iterator]
        return dict(resp.headers), chunks
    return asyncio.run(run())


# --- The production gates ---------------------------------------------------------------------

def test_production_kills_it_with_no_escape_hatch(monkeypatch):
    """Gate 1: `environment == production` is the end of the question, not a configurable."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "dev_reload", True)   # even explicitly ON
    assert settings.is_production is True
    assert settings.dev_reload_active is False
    # And there is deliberately no way to force it back on.
    assert not hasattr(settings, "allow_dev_reload_in_prod")


def test_endpoint_404s_in_production(client, monkeypatch):
    """404, not 403: outside local dev the route must be indistinguishable from absent."""
    monkeypatch.setattr(settings, "environment", "production")
    r = client.get("/api/dev/reload")
    assert r.status_code == 404


def test_endpoint_404s_when_switched_off_by_env(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_reload", False)
    assert settings.dev_reload_active is False
    assert client.get("/api/dev/reload").status_code == 404


def test_the_route_is_registered_unconditionally(client, monkeypatch):
    """Gate 3. The route must EXIST whatever the setting said at import time, so that the answer
    follows the setting per request. A conditional `include_router` would freeze it at import — the
    failure mode being an endpoint that is "gone" in one worker and live in another."""
    monkeypatch.setattr(settings, "environment", "production")
    assert "/api/dev/reload" in {getattr(r, "path", None) for r in app.routes}
    assert client.get("/api/dev/reload").status_code == 404      # registered, and still refused


def test_the_gate_is_re_read_on_every_request(monkeypatch):
    """Same process, opposite answers, driven by the setting alone."""
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(HTTPException) as err:
        dev_router._require_dev()
    assert err.value.status_code == 404
    monkeypatch.setattr(settings, "environment", "development")
    dev_router._require_dev()               # no raise


def test_localhost_gate_lives_in_app_js():
    """Gate 2 is in the browser, and it must stay un-widenable: a Cloud Run host can never be
    localhost, so a production page structurally never requests the client script."""
    js = (dev_router.FRONTEND_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert '"localhost", "127.0.0.1"' in js
    assert "/static/js/devreload.js" in js
    # The service worker must NOT register when live reload is on, or it can serve a stale asset
    # back over the file you just edited.
    assert 'if ("serviceWorker" in navigator && !DEV_RELOAD)' in js


def test_kiosk_keeps_its_service_worker_locally():
    """The kiosk's defining requirement is booting OFFLINE from cache, so it opts out of live
    reload — otherwise that path would only ever be exercised in production."""
    js = (dev_router.FRONTEND_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'location.pathname !== "/kiosk"' in js


# --- The stream itself ------------------------------------------------------------------------

def _boot_id(chunks: list[str]) -> str:
    """The `boot` value out of the opening hello frame."""
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data:"):
                return json.loads(line.split(":", 1)[1].strip() or "{}")["boot"]
    raise AssertionError("stream ended before the hello event")


def test_stream_opens_with_a_boot_id_and_unbuffered_headers():
    """The id is how the browser detects a uvicorn restart — without it, a frontend file saved while
    the backend was down lands in the new baseline and its change event can never arrive."""
    headers, chunks = _drive()
    assert headers["content-type"].startswith("text/event-stream")
    # 🔴 Without this a proxy in front of uvicorn buffers the whole stream into one blob, which is a
    # documented cross-cutting gotcha in the workspace AGENTS.md.
    assert headers["x-accel-buffering"] == "no"
    assert headers["cache-control"] == "no-cache"
    # `retry` shortens EventSource's backoff so the reconnect lands with the backend restart.
    assert "retry: 1000" in chunks[0]
    assert "event: hello" in chunks[0]
    assert _boot_id(chunks)


def test_boot_id_is_stable_within_a_process():
    """Two connections to the SAME server must agree, or every reconnect would read as a restart and
    the page would reload in a loop."""
    first_connection = _boot_id(_drive()[1])
    second_connection = _boot_id(_drive()[1])
    assert first_connection == second_connection


def test_stream_stops_when_the_browser_goes_away():
    """The generator must exit on disconnect. It polls the filesystem on a timer, so a stream that
    outlived its tab would keep walking the tree for every closed tab of the session."""
    req = _OneShotRequest(alive=1)
    _drive(req)                       # returns at all == the loop ended
    assert req._polls == 2            # one live poll, then the disconnect that broke it


# --- The watcher ------------------------------------------------------------------------------

def test_only_frontend_asset_types_are_watched(tmp_path, monkeypatch):
    """An editor swap file, a .pyc or a stray screenshot must not trigger a reload."""
    monkeypatch.setattr(dev_router, "FRONTEND_DIR", tmp_path)
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "a.css").write_text("body{}", encoding="utf-8")
    (tmp_path / "static" / "b.js").write_text("//", encoding="utf-8")
    (tmp_path / "page.html").write_text("<p>", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignored", encoding="utf-8")
    (tmp_path / "cached.pyc").write_bytes(b"\x00")
    (tmp_path / ".styles.css.swp").write_text("vim", encoding="utf-8")

    watched = set(dev_router._snapshot())
    assert watched == {"static/a.css", "static/b.js", "page.html"}


def test_missing_frontend_dir_is_not_an_error(tmp_path, monkeypatch):
    """A checkout with no frontend assets must not 500 the endpoint — the API boots without them
    (main.py mounts static with check_dir=False for the same reason)."""
    monkeypatch.setattr(dev_router, "FRONTEND_DIR", tmp_path / "nope")
    assert dev_router._snapshot() == {}


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda p: (p / "static" / "a.css").write_text("body{color:red}", encoding="utf-8"), ["static/a.css"]),
        (lambda p: (p / "static" / "new.js").write_text("//new", encoding="utf-8"), ["static/new.js"]),
        (lambda p: (p / "static" / "a.css").unlink(), ["static/a.css"]),
    ],
    ids=["edited", "added", "deleted"],
)
def test_edits_additions_and_deletions_are_all_changes(tmp_path, monkeypatch, mutate, expected):
    """🔴 A DELETION is a change too. A max-mtime shortcut would miss it entirely, and a removed
    file changes the page just as much as an edited one — which is why `_snapshot` returns a full
    mapping that is compared wholesale."""
    monkeypatch.setattr(dev_router, "FRONTEND_DIR", tmp_path)
    (tmp_path / "static").mkdir()
    css = tmp_path / "static" / "a.css"
    css.write_text("body{}", encoding="utf-8")
    # Age the pre-existing file into the past rather than bumping mtimes after the mutation. mtime
    # resolution is coarse enough on some filesystems that a same-tick rewrite compares equal, so the
    # baseline has to be visibly older — and it must be aged file by file, because bumping everything
    # afterwards marks the UNTOUCHED file as changed too and the "added" case then reports both.
    aged = css.stat().st_mtime - 10
    os.utime(css, (aged, aged))
    before = dev_router._snapshot()

    mutate(tmp_path)

    assert dev_router._changed(before, dev_router._snapshot()) == expected


def test_no_change_reports_nothing(tmp_path, monkeypatch):
    """The poll runs every 300ms; a false positive here would reload the page continuously."""
    monkeypatch.setattr(dev_router, "FRONTEND_DIR", tmp_path)
    (tmp_path / "a.css").write_text("body{}", encoding="utf-8")
    snap = dev_router._snapshot()
    assert dev_router._changed(snap, dev_router._snapshot()) == []


# --- The client's CSS/JS split -----------------------------------------------------------------

def test_client_swaps_css_and_reloads_everything_else():
    """The CSS hot-swap is the whole value on the task board: a full reload throws away the open
    card, the filters and the scroll position you are styling against."""
    js = (dev_router.FRONTEND_DIR / "static" / "js" / "devreload.js").read_text(encoding="utf-8")
    assert "swapStyles" in js
    assert "location.reload()" in js
    # A mixed batch must reload — JS has to re-run, and half-applied is worse than a reload.
    assert "paths.length > 0 && paths.every" in js
    # The local service worker is unregistered, or a reload can serve the pre-edit file from cache.
    assert "unregister()" in js
