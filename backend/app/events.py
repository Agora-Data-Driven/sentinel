"""In-process pub/sub for Server-Sent Events (live task board + notifications).

Sync request handlers (which run in a threadpool) call ``broker.publish(...)``; the SSE endpoint,
an async handler, reads from a per-connection ``asyncio.Queue``. Publishing hops back onto the event
loop thread via ``call_soon_threadsafe`` so it's safe to call from the threadpool.

Scope: this is *per process*. On multi-instance Cloud Run, a publish only reaches clients connected
to the same instance — fine for a small team (typically one warm instance); revisit with Redis
pub/sub if the service is scaled out.
"""
from __future__ import annotations

import asyncio
from typing import Any


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running loop at startup so sync handlers can publish across threads."""
        self._loop = loop

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        """Fan an event out to every subscriber. Safe to call from a sync/threadpool handler."""
        loop = self._loop
        if loop is None:
            return
        for q in list(self._subscribers):
            loop.call_soon_threadsafe(self._offer, q, event)

    @staticmethod
    def _offer(q: asyncio.Queue, event: dict[str, Any]) -> None:
        # Drop on a slow/full consumer rather than blocking the loop.
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


broker = EventBroker()
