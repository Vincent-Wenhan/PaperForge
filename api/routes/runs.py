"""Runs API routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.tasks import get_run_task_manager
from paperforge.storage.db import get_storage

router = APIRouter()


class RunCreate(BaseModel):
    title: str | None = None


class RunUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class Run(BaseModel):
    id: str
    title: str
    status: str
    phase: str = "init"
    pinned: bool = False
    archived_at: str | None = None
    last_message_at: str | None = None
    created_at: str
    updated_at: str


def _to_run(row: dict) -> Run:
    return Run(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        phase=row.get("phase") or "init",
        pinned=bool(row.get("pinned", 0)),
        archived_at=row.get("archived_at"),
        last_message_at=row.get("last_message_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_message(row: dict[str, Any]) -> dict[str, Any]:
    """Return one stable message shape for initial hydration and SSE merges."""
    message = dict(row)
    public_id = message.get("public_id") or f"msg_{message.get('id')}"
    message["public_id"] = public_id
    message["id"] = public_id
    message["content"] = message.get("content") or ""
    message["status"] = message.get("status") or "completed"
    if message.get("parts") is None:
        message["parts"] = []
    return message


def _to_artifact(storage: Any, row: dict[str, Any]) -> dict[str, Any]:
    artifact = storage.get_artifact(row["id"]) or dict(row)
    artifact.setdefault("metadata", {})
    artifact.setdefault("data", {})
    return artifact


def _to_approval(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "approval_id": row["id"],
        "run_id": row["run_id"],
        "tool": row["tool_name"],
        "args": row.get("args") or {},
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row.get("resolved_at"),
}


def _to_preview(sandbox: dict[str, Any] | None) -> dict[str, Any]:
    if sandbox is None:
        return {"status": "idle", "sandbox_id": None}
    status = sandbox.get("status")
    preview_status = sandbox.get("preview_status")
    if preview_status == "idle" and status in {"pending", "starting", "running"}:
        preview_status = "starting"
    elif preview_status == "idle" and status == "stopped":
        preview_status = "stopped"
    elif preview_status == "idle" and status in {"error", "failed"}:
        preview_status = "degraded"
    elif preview_status not in {"idle", "starting", "running", "degraded", "stopped", "error"}:
        preview_status = (
            "starting"
            if status in {"pending", "starting", "running"}
            else "degraded"
            if status in {"error", "failed"}
            else "stopped"
        )
    return {
        "status": preview_status,
        "sandbox_id": sandbox.get("id"),
        "preview_url": (
            sandbox.get("preview_url") or f"/api/preview/{sandbox['id']}/"
            if preview_status == "running"
            else None
        ),
        "error": sandbox.get("error"),
    }


def _to_task(row: dict[str, Any]) -> dict[str, Any]:
    task = dict(row)
    task.setdefault("task_id", task.get("id"))
    return task


@router.post("", response_model=Run)
async def create_run(req: RunCreate) -> Run:
    storage = get_storage()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    # Default title is "New Run" so the auto-title logic in messages.py
    # can detect first-message and rename. User-supplied titles win.
    title = req.title or "New Run"
    run = storage.create_run(run_id=run_id, title=title, status="active")
    return _to_run(run)


@router.get("", response_model=list[Run])
async def list_runs(
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
    archived: bool = False,
) -> list[Run]:
    storage = get_storage()
    rows = storage.list_runs(limit=limit, offset=offset)
    out: list[Run] = []
    for r in rows:
        is_archived = bool(r.get("archived_at"))
        if is_archived != archived:
            continue
        if query:
            q = query.lower()
            if q not in (r.get("title") or "").lower() and q not in r["id"].lower():
                continue
        out.append(_to_run(r))
    return out


@router.get("/{run_id}", response_model=Run)
async def get_run(run_id: str) -> Run:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_run(run)


@router.patch("/{run_id}", response_model=Run)
async def update_run(run_id: str, req: RunUpdate) -> Run:
    storage = get_storage()
    run = storage.update_run(
        run_id=run_id,
        title=req.title,
        pinned=req.pinned,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    await EventEmitter(run_id, get_event_manager()).run_updated(
        title=run.get("title"),
        pinned=bool(run.get("pinned", 0)),
    )
    return _to_run(run)


@router.post("/{run_id}/archive", response_model=Run)
async def archive_run(run_id: str) -> Run:
    storage = get_storage()
    run = storage.archive_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    await EventEmitter(run_id, get_event_manager()).run_updated(
        archived_at=run.get("archived_at"),
    )
    return _to_run(run)


@router.post("/{run_id}/restore", response_model=Run)
async def restore_run(run_id: str) -> Run:
    storage = get_storage()
    run = storage.restore_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    await EventEmitter(run_id, get_event_manager()).run_updated(
        archived_at=run.get("archived_at"),
    )
    return _to_run(run)


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    task_manager = get_run_task_manager()
    await task_manager.cancel_and_wait(run_id)
    storage.delete_run(run_id)
    return {"status": "deleted", "run_id": run_id}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] in {"cancelled", "done"}:
        raise HTTPException(status_code=409, detail="Run is not active")

    task_manager = get_run_task_manager()
    cancelled = await task_manager.cancel_and_wait(run_id)
    if not cancelled and run["status"] != "running":
        raise HTTPException(status_code=409, detail="Run is not active")

    previous_status = run["status"]
    storage.update_run_status(run_id, "cancelled")
    event_manager = get_event_manager()
    emitter = EventEmitter(run_id=run_id, manager=event_manager)
    await emitter.run_status_changed("cancelled", previous_status)
    await emitter.run_finished()
    return {"status": "cancelled", "run_id": run_id}


@router.post("/{run_id}/papers/{paper_id}")
async def attach_paper(run_id: str, paper_id: str) -> dict:
    """Attach a library paper to a run (doc 4.4)."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    storage.attach_paper_to_run(run_id, paper_id)
    return {"status": "attached", "run_id": run_id, "paper_id": paper_id}


@router.delete("/{run_id}/papers/{paper_id}")
async def detach_paper(run_id: str, paper_id: str) -> dict:
    """Detach a paper from a run (doc 4.4)."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    removed = storage.detach_paper_from_run(run_id, paper_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Paper not attached to this run")
    return {"status": "detached", "run_id": run_id, "paper_id": paper_id}


@router.get("/{run_id}/papers")
async def list_run_papers(run_id: str) -> dict:
    """List papers attached to a run."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    papers = storage.list_run_papers(run_id)
    return {"papers": papers}


@router.get("/{run_id}/state")
async def get_run_state(run_id: str) -> dict:
    """Aggregate run state in one request (doc 1A.6).

    Returns run, messages, artifacts, sandbox, pending_approvals,
    and event_cursor so the frontend can hydrate in a single shot
    and then connect SSE with after_seq=event_cursor.
    """
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    messages = [_to_message(row) for row in storage.list_messages(run_id)]
    artifacts = [
        _to_artifact(storage, row)
        for row in storage.list_artifacts(run_id=run_id)
    ]
    sandbox = storage.get_latest_sandbox_for_run(run_id)
    approvals = [
        _to_approval(row)
        for row in storage.list_approvals(run_id=run_id, status="pending")
    ]
    all_approvals = [
        _to_approval(row)
        for row in storage.list_approvals(run_id=run_id)
    ]
    tasks = [_to_task(row) for row in storage.list_tasks(run_id)]
    event_cursor = storage.get_max_event_seq(run_id)

    return {
        "run": _to_run(run).model_dump(),
        "messages": messages,
        "artifacts": artifacts,
        "sandbox": sandbox,
        "preview": _to_preview(sandbox),
        "pending_approvals": approvals,
        "approvals": all_approvals,
        "tasks": tasks,
        "event_cursor": event_cursor,
    }


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    storage = get_storage()
    return storage.list_messages(run_id)


@router.get("/{run_id}/artifacts")
async def list_artifacts(run_id: str, artifact_type: str | None = None) -> list[dict]:
    storage = get_storage()
    return storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)
