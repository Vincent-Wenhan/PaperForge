"""Events SSE API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from paperforge.orchestrator.events import get_event_manager
from paperforge.storage.db import get_storage

router = APIRouter()


def _last_event_id(request: Request) -> int:
    raw = request.headers.get("Last-Event-ID") or "0"
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    """Stream SSE events for a run.

    Emits a `RunEvent` envelope per event:
    ```json
    {
      "id": "evt_...",
      "seq": 1,
      "run_id": "run_...",
      "type": "message.delta",
      "ts": 1780000000,
      "payload": { ... }
    }
    ```

    The server also sends the SSE `id:` field so the browser's native
    EventSource includes it in `Last-Event-ID` on reconnect, allowing
    dedup on the client side.
    """
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    event_manager = get_event_manager()
    queue = event_manager.register(run_id)

    last_seq = _last_event_id(request)

    async def event_stream() -> AsyncIterator[str]:
        try:
            # On reconnect/replay, yield events from history with seq > last_seq.
            for event in event_manager.get_history(run_id):
                if event.seq <= last_seq:
                    continue
                payload = {
                    "id": event.id,
                    "seq": event.seq,
                    "run_id": event.run_id,
                    "type": event.type,
                    "ts": event.ts,
                    "payload": event.data,
                }
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if event.seq <= last_seq:
                        # Skip already-acknowledged events on reconnect.
                        continue
                    payload = {
                        "id": event.id,
                        "seq": event.seq,
                        "run_id": event.run_id,
                        "type": event.type,
                        "ts": event.ts,
                        "payload": event.data,
                    }
                    yield f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            event_manager.unregister(run_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
