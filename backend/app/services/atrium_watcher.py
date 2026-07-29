"""Atrium Watcher bridge -- lets a worker's Mentor Library import a transcript Atrium already
archived, instead of hand-pasting one.

Atrium's team-only "Watcher" tab (services/portal/dash/watcher.py) watches YouTube channels and
auto-fetches every video's transcript (no API key, no copy-paste). This module reads that archive
over the same signed HMAC transport `atrium_tasks.py` uses (see `atrium_bridge.py`).

🔴 It reads EVERY workspace by default. Watcher's registry is per-client, but a MENTOR is nobody's
client -- the creators a worker learns from live in whichever workspace the team added them to.
`atrium_watcher_client_key` is therefore an OPTIONAL narrowing filter (unset = all workspaces), not
a required scope. It used to be required and defaulted to "agora"; no such workspace has ever
existed, so the picker showed "No creators watched in Atrium yet" while 15 creators sat archived
across four other workspaces. Channel ids arrive namespaced "<client_key>:<channel_id>" and are
passed straight back, so this module never has to know which workspace a channel came from.

READ-ONLY and fail-SOFT like the task bridge: an unset secret/URL, a timeout, a non-200 or a
malformed body all degrade to "" / [] / None so a Mentor Library page never breaks because Atrium
is unreachable -- the worker just sees no Atrium creators and can still paste a transcript by hand.
"""

from __future__ import annotations

import logging

from ..config import settings
from . import atrium_bridge
from .atrium_bridge import enabled

log = logging.getLogger(__name__)


def client_key() -> str:
    """The OPTIONAL workspace filter. "" (the default) means every Atrium workspace."""
    return (getattr(settings, "atrium_watcher_client_key", "") or "").strip()


def _scope(**params) -> dict:
    """Request params, carrying `client` only when a deploy pins one workspace."""
    key = client_key()
    if key:
        params["client"] = key
    return params


def ready() -> bool:
    """True when the bridge is configured. The workspace filter is optional, so it isn't checked."""
    return enabled()


def list_channels() -> list[dict]:
    """Every watched channel Atrium holds. [] on any failure -- never raises."""
    if not enabled():
        return []
    code, body = atrium_bridge.call("watcher-channels", "/api/internal/watcher/channels",
                                    params=_scope())
    if code != 200:
        if code:
            log.warning("atrium watcher channels fetch returned %s", code)
        return []
    channels = body.get("channels")
    return channels if isinstance(channels, list) else []


def list_videos(channel_id: str) -> list[dict]:
    """One channel's videos (light fields, no transcript body). [] on any failure."""
    if not channel_id or not enabled():
        return []
    code, body = atrium_bridge.call("watcher-videos", "/api/internal/watcher/videos",
                                    params=_scope(channel=channel_id))
    if code != 200:
        if code:
            log.warning("atrium watcher videos fetch returned %s", code)
        return []
    videos = body.get("videos")
    return videos if isinstance(videos, list) else []


def get_transcript(channel_id: str, video_id: str) -> dict | None:
    """{"title", "url", "transcript"} for one video, or None (not found / no transcript / offline)."""
    if not channel_id or not video_id or not enabled():
        return None
    code, body = atrium_bridge.call("watcher-transcript", "/api/internal/watcher/transcript",
                                    params=_scope(channel=channel_id, video=video_id))
    if code != 200 or not body.get("transcript"):
        if code and code != 404:
            log.warning("atrium watcher transcript fetch returned %s", code)
        return None
    return {"title": body.get("title") or "", "url": body.get("url") or "",
            "transcript": body.get("transcript") or ""}


# A whole channel at once, for "Import all". Atrium returns a byte-budgeted page plus a
# `next_offset` to resume from (0 = done), because one creator's archive can run to ~12 MB of text.
# Generous timeout: this moves megabytes, unlike the light listing calls above.
BULK_TIMEOUT = 180
_MAX_PAGES = 40                       # runaway guard -- 40 * 8 MiB is far past any real archive


def list_transcripts(channel_id: str) -> list[dict]:
    """EVERY fetched transcript in one channel, following Atrium's paging. [] on any failure.

    Fail-soft like the rest of this module, with one deliberate difference: a page that fails
    mid-way returns what was already collected rather than discarding it, so a partial import still
    banks real work instead of throwing away several megabytes over one bad response."""
    if not channel_id or not enabled():
        return []
    items: list[dict] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        code, body = atrium_bridge.call("watcher-transcripts",
                                        "/api/internal/watcher/transcripts",
                                        params=_scope(channel=channel_id, offset=offset),
                                        timeout=BULK_TIMEOUT)
        if code != 200:
            if code:
                log.warning("atrium watcher transcripts fetch returned %s", code)
            break
        page = body.get("transcripts")
        if isinstance(page, list):
            items.extend(page)
        try:
            offset = int(body.get("next_offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        if offset <= 0:
            break
    return items
