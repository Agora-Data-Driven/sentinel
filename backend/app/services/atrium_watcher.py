"""Atrium Watcher bridge -- lets a worker's Mentor Library import a transcript Atrium already
archived, instead of hand-pasting one.

Atrium's team-only "Watcher" tab (services/portal/dash/watcher.py) watches YouTube channels and
auto-fetches every video's transcript (no API key, no copy-paste). This module reads that archive
for ONE client workspace (`atrium_watcher_client_key`, e.g. "agora") over the same signed HMAC
transport `atrium_tasks.py` uses (see `atrium_bridge.py`).

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
    return (getattr(settings, "atrium_watcher_client_key", "") or "").strip()


def ready() -> bool:
    """True when the bridge is configured AND a client workspace is set to read from."""
    return enabled() and bool(client_key())


def list_channels() -> list[dict]:
    """Every watched channel in the configured workspace. [] on any failure -- never raises."""
    key = client_key()
    if not key or not enabled():
        return []
    code, body = atrium_bridge.call("watcher-channels", "/api/internal/watcher/channels",
                                    params={"client": key})
    if code != 200:
        if code:
            log.warning("atrium watcher channels fetch returned %s", code)
        return []
    channels = body.get("channels")
    return channels if isinstance(channels, list) else []


def list_videos(channel_id: str) -> list[dict]:
    """One channel's videos (light fields, no transcript body). [] on any failure."""
    key = client_key()
    if not key or not channel_id or not enabled():
        return []
    code, body = atrium_bridge.call("watcher-videos", "/api/internal/watcher/videos",
                                    params={"client": key, "channel": channel_id})
    if code != 200:
        if code:
            log.warning("atrium watcher videos fetch returned %s", code)
        return []
    videos = body.get("videos")
    return videos if isinstance(videos, list) else []


def get_transcript(channel_id: str, video_id: str) -> dict | None:
    """{"title", "url", "transcript"} for one video, or None (not found / no transcript / offline)."""
    key = client_key()
    if not key or not channel_id or not video_id or not enabled():
        return None
    code, body = atrium_bridge.call("watcher-transcript", "/api/internal/watcher/transcript",
                                    params={"client": key, "channel": channel_id, "video": video_id})
    if code != 200 or not body.get("transcript"):
        if code and code != 404:
            log.warning("atrium watcher transcript fetch returned %s", code)
        return None
    return {"title": body.get("title") or "", "url": body.get("url") or "",
            "transcript": body.get("transcript") or ""}
