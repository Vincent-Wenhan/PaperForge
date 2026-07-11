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


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    """Stream SSE events for a run."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    event_manager = get_event_manager()
    queue = event_manager.register(run_id)

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    payload = {
                        "type": event.type,
                        "data": event.data,
                        "run_id": event.run_id,
                    }
                    yield f"event: {event.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
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
