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
    paper_ids: list[str] = []


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: MessageCreate) -> dict:
    """Send a user message to the run. Triggers the orchestrator asynchronously.

    `paper_ids` attach library papers as explicit context so the LLM never
    has to guess server file paths.
    """
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Reject if a task is already running for this run; the caller must stop
    # the existing task before sending a new message. This prevents silent
    # cancellation of in-flight orchestrator work.
    task_manager = get_run_task_manager()
    if task_manager.is_running(run_id):
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this run. Cancel it first.",
        )

    # API layer owns user message persistence; orchestrator must not duplicate it.
    storage.add_message(run_id=run_id, role="user", content=req.content)

    orchestrator = Orchestrator()
    task_manager.start(run_id, orchestrator.run(run_id=run_id, user_message=req.content))

    return {"status": "queued", "run_id": run_id}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List all messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)
