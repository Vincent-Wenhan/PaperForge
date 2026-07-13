"""Messages API routes."""

from __future__ import annotations

import logging
import uuid

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
    public_id: str | None = None


def _derive_title(content: str, max_len: int = 50) -> str:
    """Ponytail: derive a short title from the user's first message.

    Strip whitespace, take the first line, truncate with ellipsis. No
    need for an LLM call when a heuristic this simple works.
    """
    line = content.strip().splitlines()[0] if content.strip() else ""
    if not line:
        return "New Run"
    if len(line) <= max_len:
        return line
    return line[: max_len - 1].rstrip() + "…"


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
    message = storage.add_message(
        run_id=run_id,
        role="user",
        content=req.content,
        public_id=req.public_id,
    )

    # Auto-generate run title from the first user message (doc 6.5).
    # Only update if the title is still the default placeholder so we
    # never overwrite a user's manual rename.
    current_title = run.get("title") or ""
    if current_title in ("", "Untitled Run", "New Run"):
        new_title = _derive_title(req.content)
        storage.update_run(run_id=run_id, title=new_title)

    # Attach any new papers to this run as explicit context (doc 4.3/4.4).
    for paper_id in req.paper_ids:
        storage.attach_paper_to_run(run_id, paper_id)

    orchestrator = Orchestrator()
    task_manager.start(run_id, orchestrator.run(run_id=run_id, user_message=req.content))

    return {
        "status": "queued",
        "run_id": run_id,
        "message": message,
    }


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List all messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)
