"""Messages API routes."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.tasks import get_run_queue, get_run_task_manager
from paperforge.storage.db import get_storage

logger = logging.getLogger(__name__)
router = APIRouter()

_run_queue = get_run_queue()


class MessageCreate(BaseModel):
    content: str
    paper_ids: list[str] = []
    public_id: str | None = None
    mode: Literal["start", "queue", "interrupt"] = "start"


class MessageCreateResult(BaseModel):
    status: str
    run_id: str
    message: dict
    task: dict
    task_id: str
    event_cursor: int


def _task(task: dict) -> dict:
    result = dict(task)
    result["task_id"] = result.get("task_id", result.get("id"))
    return result


def _message(row: dict) -> dict:
    message = dict(row)
    public_id = message.get("public_id") or f"msg_{message.get('id')}"
    message["public_id"] = public_id
    message["id"] = public_id
    message["content"] = message.get("content") or ""
    message["status"] = message.get("status") or "completed"
    return message


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


@router.post("/{run_id}/messages", response_model=MessageCreateResult)
async def send_message(run_id: str, req: MessageCreate) -> MessageCreateResult:
    """Send a user message to the run. Triggers the orchestrator asynchronously.

    `paper_ids` attach library papers as explicit context so the LLM never
    has to guess server file paths.

    Returns the full created ``message`` and ``task`` (not just ``task_id``)
    so the client can reconcile its optimistic user message and upsert the new
    Task without a second round-trip. ``event_cursor`` is the run-level max seq
    so the client can resume SSE from that point.
    """
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Reject with 409 only if the caller explicitly wants to start a fresh task
    # while one is already running. Follow-ups queue instead; interrupts cancel
    # the in-flight task first.
    task_manager = get_run_task_manager()
    if task_manager.is_running(run_id) and req.mode == "start":
        raise HTTPException(
            status_code=409,
            detail="A task is already running for this run. Cancel it or send a follow-up.",
        )

    if req.mode == "interrupt":
        await _run_queue.cancel_and_wait(run_id)

    # Run = persistent thread. A completed run keeps its workspace; the
    # new message is just the next task in the same thread. Phase is a UI
    # display concern, not a reset trigger.
    current_phase = storage.get_run_phase(run_id)
    created = storage.create_user_task(
        run_id=run_id,
        content=req.content,
        public_id=req.public_id,
        phase=current_phase,
        priority=100 if req.mode == "interrupt" else 0,
    )
    message = created.message
    task = created.task

    # Persist+broadcast task.created so a live client sees the Task before any
    # message.started arrives (projectTurns must never drop an unknown task_id).
    task_emitter = EventEmitter(run_id=run_id, manager=get_event_manager(), task_id=task["id"])
    await task_emitter.task_created(_task(task))

    # Auto-generate run title from the first user message.
    # Only update if the title is still the default placeholder so we
    # never overwrite a user's manual rename.
    current_title = run.get("title") or ""
    if current_title in ("", "Untitled Run", "New Run"):
        new_title = _derive_title(req.content)
        updated_run = storage.update_run(run_id=run_id, title=new_title)
        await EventEmitter(run_id, get_event_manager()).run_updated(
            title=updated_run.get("title") if updated_run else new_title,
        )

    # Attach any new papers to this run as explicit context.
    for paper_id in req.paper_ids:
        storage.attach_paper_to_run(run_id, paper_id)

    # The queue stores only the task id and rebuilds execution from the DB
    # task row, so a restart can recover queued work (doc 8).
    await _run_queue.enqueue(
        run_id,
        task["id"],
    )
    return MessageCreateResult(
        status="queued",
        run_id=run_id,
        message=_message(message),
        task=_task(task),
        task_id=task["id"],
        event_cursor=storage.get_max_event_seq(run_id),
    )


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List all messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)
