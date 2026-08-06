"""Live reload for local development — `GET /api/dev/reload`.

Why this exists: the frontend is **vanilla JS with no build step** (AGENTS.md §8), which is a
deliberate choice and not one this file changes. The cost of it is that nothing watches the
frontend, so `uvicorn --reload` restarts Python on every save while a CSS or JS edit needs a manual
refresh — and, worse, a refresh that the service worker may answer from cache (§5, "Frontend change
deployed but the browser shows the old version"). This closes that gap without a bundler: the server
watches `frontend/`, the browser listens, and `devreload.js` decides what to do with each change.

**A stylesheet edit is swapped in place, not reloaded** — that is what makes it useful on the task
board, where a full reload throws away the open card, the filters and the scroll position.

🔴 THREE GATES KEEP THIS OUT OF PRODUCTION, and they are independent on purpose:

1. `settings.dev_reload_active` is False whenever `environment == "production"`, with no escape
   hatch (config.py). Every route here 404s.
2. `frontend/static/js/app.js` only loads the client script when `location.hostname` is localhost —
   so even a misconfigured deploy serves a page that never asks.
3. The router is registered unconditionally but every handler re-checks gate 1 at REQUEST time, not
   at import time. A conditional `include_router` would make the route's existence depend on the
   value of a setting when the module was imported, which is exactly the kind of thing that reads as
   "the endpoint is gone" while a stale worker still serves it.

No new dependency: this polls mtimes rather than pulling in `watchdog`. The tree is ~40 files, the
walk is a few milliseconds, and it only runs while a browser tab is actually connected — the same
reasoning that keeps the rate limiter hand-rolled (AGENTS.md §9).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(prefix="/api/dev", tags=["dev"])

# 🔴 Minted once per PROCESS, and that is the whole trick: `uvicorn --reload` replaces the process on
# every Python edit, so a new id is how the browser learns the backend restarted underneath it.
#
# It exists because a reconnecting stream rebuilds its baseline snapshot from disk. Any frontend file
# saved while uvicorn was down is therefore already in the new baseline and compares equal forever —
# so without this, "edit a .py and a .js together" reloaded Python and silently dropped the JS. The
# client compares this value across `hello` events and reloads when it changes, which also means a
# pure backend edit now refreshes the page against the new API instead of leaving a stale tab.
_BOOT_ID = str(uuid.uuid4())

# app/routers/dev.py -> parents[2] == sentinel/backend, so parents[3] == sentinel/
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

# What a change to each kind of file means for the browser. Anything not listed is ignored, so an
# editor's swap file, a .pyc or a stray screenshot in the tree cannot trigger a reload.
_WATCHED = (".css", ".js", ".html", ".json", ".svg")

# How often the tree is walked. 300ms is under the threshold where a save feels like it "didn't
# work" while being long enough that the walk is free. Not configurable on purpose — one less knob.
_POLL_SECONDS = 0.3

# Matches stream.py: keeps proxies and the browser from closing an idle stream.
_KEEPALIVE_SECONDS = 20


def _require_dev() -> None:
    """404 — not 403 — when live reload is off.

    A 403 would confirm the endpoint exists, and this route is meant to be indistinguishable from
    absent outside local development. It is also what makes gate 3 above safe: the check happens per
    request, so the answer follows the setting rather than whatever it was at import time.
    """
    if not settings.dev_reload_active:
        raise HTTPException(status_code=404, detail="Not Found")


def _snapshot() -> dict[str, float]:
    """`{relative path: mtime}` for every watched file under frontend/.

    Deletions matter as much as edits — a removed file changes the page — so this is a full mapping
    compared wholesale, not a max-mtime shortcut. `rglob` on a missing directory yields nothing
    rather than raising, which keeps the endpoint working in a checkout with no frontend assets.
    """
    out: dict[str, float] = {}
    if not FRONTEND_DIR.is_dir():
        return out
    for path in FRONTEND_DIR.rglob("*"):
        if path.suffix.lower() not in _WATCHED:
            continue
        try:
            out[str(path.relative_to(FRONTEND_DIR)).replace("\\", "/")] = path.stat().st_mtime
        except OSError:
            # A file being written to right now (or deleted between the walk and the stat) is not an
            # error — the next poll, 300ms away, sees whatever it settled into.
            continue
    return out


def _changed(before: dict[str, float], after: dict[str, float]) -> list[str]:
    """Paths that were added, removed, or whose mtime moved."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


@router.get("/reload")
async def reload_stream(request: Request):
    """SSE: one `change` event per batch of edits, carrying the paths that changed.

    Deliberately UNAUTHENTICATED, unlike `/api/stream`. Reload has to work on `/login` and `/kiosk`
    — pages that run with `data-shell="off"` and no session — and it has to work while you are
    signed out, which is exactly when you are editing the login page. It leaks the relative paths of
    files in the frontend directory to whoever can reach localhost, which is the person editing them.
    """
    _require_dev()
    known = _snapshot()

    async def gen():
        nonlocal known
        # `retry` tunes EventSource's own backoff, so a uvicorn restart reconnects in ~1s instead of
        # the browser's 3s default — the backend reload and the frontend reload then land together.
        yield f"retry: 1000\nevent: hello\ndata: {json.dumps({'boot': _BOOT_ID})}\n\n"
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(_POLL_SECONDS)
            current = _snapshot()
            paths = _changed(known, current)
            if paths:
                known = current
                idle = 0.0
                yield f"event: change\ndata: {json.dumps({'paths': paths})}\n\n"
                continue
            idle += _POLL_SECONDS
            if idle >= _KEEPALIVE_SECONDS:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        # 🔴 `X-Accel-Buffering: no` is not optional even locally — it is what stops a proxy in front
        # of uvicorn from buffering the stream into one blob (AGENTS.md §4, the cross-cutting
        # "Streaming arrives as one blob" gotcha). Same headers stream.py sends, for the same reason.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
