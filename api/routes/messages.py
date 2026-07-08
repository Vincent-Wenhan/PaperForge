"""Messages API routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.loop import Orchestrator
from paperforge.storage.db import get_storage

logger = logging.getLogger(__name__)
router = APIRouter()


class MessageCreate(BaseModel):
    content: str


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: MessageCreate) -> dict:
    """Send a user message to the run. Triggers the orchestrator asynchronously."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Save user message
    storage.add_message(run_id=run_id, role="user", content=req.content)

    # Start orchestrator in background
    async def _run_orchestrator() -> None:
        try:
            orchestrator = Orchestrator()
            await orchestrator.run(run_id=run_id, user_message=req.content)
        except Exception as e:
            logger.exception(f"Orchestrator error: {e}")

    asyncio.create_task(_run_orchestrator())

    return {"status": "queued", "run_id": run_id}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List all messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)
