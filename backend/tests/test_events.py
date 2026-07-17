"""SSE event broker + stream endpoint auth.

The streamed happy-path is verified live (curl) since a TestClient GET would block on the infinite
generator; here we cover the broker logic and the auth gate (which rejects before streaming starts).
"""
from __future__ import annotations

import asyncio

from app.events import EventBroker


def test_stream_requires_auth(client):
    # No session cookie -> 401 is raised before the stream generator ever runs (so it returns fast).
    assert client.get("/api/stream").status_code == 401


def test_subscribe_and_unsubscribe_manage_the_set():
    b = EventBroker()

    async def go():
        q = await b.subscribe()
        assert b.subscriber_count == 1
        b.unsubscribe(q)
        assert b.subscriber_count == 0

    asyncio.run(go())


def test_publish_without_bound_loop_is_noop():
    b = EventBroker()  # never bound to a loop
    b.publish({"type": "task", "task_id": 1})  # must not raise


def test_offer_drops_when_queue_full():
    q = asyncio.Queue(maxsize=1)
    q.put_nowait({"first": True})
    EventBroker._offer(q, {"second": True})  # full -> dropped, no exception
    assert q.qsize() == 1


def test_publish_delivers_to_subscriber():
    b = EventBroker()

    async def go():
        b.bind_loop(asyncio.get_running_loop())
        q = await b.subscribe()
        b.publish({"type": "task", "action": "moved", "task_id": 7})
        event = await asyncio.wait_for(q.get(), timeout=1.0)
        assert event["task_id"] == 7 and event["action"] == "moved"

    asyncio.run(go())
