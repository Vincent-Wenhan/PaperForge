"""Runs API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.events import get_event_manager
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


@router.post("", response_model=Run)
async def create_run(req: RunCreate) -> Run:
    storage = get_storage()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    title = req.title or "Untitled Run"
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
    return _to_run(run)


@router.post("/{run_id}/archive", response_model=Run)
async def archive_run(run_id: str) -> Run:
    storage = get_storage()
    run = storage.archive_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_run(run)


@router.post("/{run_id}/restore", response_model=Run)
async def restore_run(run_id: str) -> Run:
    storage = get_storage()
    run = storage.restore_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_run(run)


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    task_manager = get_run_task_manager()
    task_manager.cancel(run_id)
    storage.delete_run(run_id)
    return {"status": "deleted", "run_id": run_id}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    task_manager = get_run_task_manager()
    cancelled = task_manager.cancel(run_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Run is not active")
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

    messages = storage.list_messages(run_id)
    artifacts = storage.list_artifacts(run_id=run_id)

    sandboxes = storage.list_sandboxes()
    run_sandboxes = [s for s in sandboxes if s.get("run_id") == run_id]
    sandbox = run_sandboxes[0] if run_sandboxes else None

    approvals = storage.list_approvals(run_id=run_id, status="pending")

    event_manager = get_event_manager()
    history = event_manager.get_history(run_id)
    event_cursor = max((e.seq for e in history), default=0)

    return {
        "run": run,
        "messages": messages,
        "artifacts": artifacts,
        "sandbox": sandbox,
        "pending_approvals": approvals,
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
