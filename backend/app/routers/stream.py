"""Server-Sent Events endpoint for the live board + notifications."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..events import broker
from ..models import User
from ..security import get_current_user

router = APIRouter(prefix="/api", tags=["stream"])

_KEEPALIVE_SECONDS = 20


@router.get("/stream")
async def stream(request: Request, user: User = Depends(get_current_user)):
    """Long-lived SSE stream. Emits `task` / `notification` events; comments keep it alive."""
    queue = await broker.subscribe()

    async def gen():
        # Tell the client the stream is live, and hint EventSource's reconnect backoff.
        yield "retry: 3000\nevent: hello\ndata: {}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # comment line; keeps proxies from closing the connection
                    continue
                etype = event.get("type", "message")
                yield f"event: {etype}\ndata: {json.dumps(event)}\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
