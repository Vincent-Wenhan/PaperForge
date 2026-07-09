"""Artifacts API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from paperforge.storage.db import get_storage

router = APIRouter()


@router.get("")
async def list_artifacts(run_id: str | None = None, artifact_type: str | None = None) -> list[dict]:
    """List artifacts, optionally filtered by run_id and/or type."""
    storage = get_storage()
    return storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str) -> dict:
    """Get an artifact by ID."""
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
