"""Runs API routes."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    storage = get_storage()
    return storage.list_messages(run_id)


@router.get("/{run_id}/artifacts")
async def list_artifacts(run_id: str, artifact_type: str | None = None) -> list[dict]:
    storage = get_storage()
    return storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)
