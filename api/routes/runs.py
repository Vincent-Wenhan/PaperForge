"""Runs API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()


class RunCreate(BaseModel):
    title: str | None = None


class Run(BaseModel):
    id: str
    title: str
    status: str
    created_at: str
    updated_at: str


@router.post("", response_model=Run)
async def create_run(req: RunCreate) -> Run:
    """Create a new run."""
    storage = get_storage()
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    title = req.title or "Untitled Run"
    run = storage.create_run(run_id=run_id, title=title, status="active")
    return Run(
        id=run["id"],
        title=run["title"],
        status=run["status"],
        created_at=run["created_at"],
        updated_at=run["updated_at"],
    )


@router.get("")
async def list_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    """List all runs."""
    storage = get_storage()
    return storage.list_runs(limit=limit, offset=offset)


@router.get("/{run_id}")
async def get_run(run_id: str) -> dict:
    """Get a run by ID."""
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.delete("/{run_id}")
async def delete_run(run_id: str) -> dict:
    """Delete a run."""
    storage = get_storage()
    storage.delete_run(run_id)
    return {"status": "deleted"}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> list[dict]:
    """List messages in a run."""
    storage = get_storage()
    return storage.list_messages(run_id)


@router.get("/{run_id}/artifacts")
async def list_artifacts(run_id: str, artifact_type: str | None = None) -> list[dict]:
    """List artifacts in a run."""
    storage = get_storage()
    return storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)
