"""Messages API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.loop import Orchestrator
from paperforge.orchestrator.tasks import get_run_task_manager
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

    # API layer owns user message persistence; orchestrator must not duplicate it.
    storage.add_message(run_id=run_id, role="user", content=req.content)

    task_manager = get_run_task_manager()
    orchestrator = Orchestrator()
    task_manager.start(run_id, orchestrator.run(run_id=run_id, user_message=req.content))

    return {"status": "queued", "run_id": run_id}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List all messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)
