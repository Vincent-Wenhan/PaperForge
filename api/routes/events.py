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


def _encode_sse(row: dict) -> str:
    envelope = {
        "id": row["id"],
        "seq": row["seq"],
        "run_id": row["run_id"],
        "type": row["type"],
        "ts": row.get("created_at"),
        "payload": row.get("data") or {},
    }
    return (
        f"id: {row['seq']}\n"
        f"event: {row['type']}\n"
        f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"
    )


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after_seq: int | None = None,
) -> StreamingResponse:
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

    Cursor-based resume is supported via either:
    - `?after_seq=N` query parameter, or
    - `Last-Event-ID` HTTP header (browser-native EventSource sets this)
    """
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    event_manager = get_event_manager()
    queue = event_manager.register(run_id)

    # A browser reconnect may provide a newer Last-Event-ID than the original
    # query string. Always resume from the furthest durable cursor.
    cursor = max(after_seq or 0, _last_event_id(request))

    async def event_stream() -> AsyncIterator[str]:
        try:
            # 1) Snapshot the DB upper bound BEFORE consuming the live
            #    queue. This prevents a race where an event is persisted
            #    after our snapshot but before we register the queue,
            #    which would cause us to miss it.
            upper_bound = await asyncio.to_thread(
                storage.get_max_event_seq, run_id
            )

            # 2) Replay persisted events with seq > cursor AND seq <= upper_bound.
            rows = await asyncio.to_thread(
                storage.list_run_events,
                run_id,
                cursor,
                5000,
                upper_bound,
            )
            for row in rows:
                if row["seq"] <= cursor:
                    continue
                cursor = row["seq"]
                yield _encode_sse(row)

            # 3) Consume the live queue, skipping events already replayed.
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue

                if event.seq <= cursor:
                    continue
                cursor = event.seq

                # Build a row-like dict so we can reuse _encode_sse.
                row = {
                    "id": event.id,
                    "seq": event.seq,
                    "run_id": event.run_id or run_id,
                    "type": event.type,
                    "data": event.data,
                    "created_at": event.ts,
                }
                yield _encode_sse(row)
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
