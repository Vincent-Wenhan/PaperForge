"""Artifacts API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from paperforge.storage.db import get_storage

router = APIRouter()


@router.get("")
async def list_artifacts(
    run_id: str | None = None,
    artifact_type: str | None = None,
    include_data: bool = False,
) -> list[dict]:
    """List artifacts, optionally filtered by run_id and/or type.

    When include_data=true, each artifact dict is augmented with its `data`
    payload loaded from the JSON file. This lets the frontend render artifact
    content in a single round-trip instead of N follow-up GETs.
    """
    storage = get_storage()
    rows = storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)
    if not include_data:
        return rows

    out: list[dict] = []
    for row in rows:
        d = dict(row)
        path = Path(d.get("path") or "")
        if path.exists():
            try:
                d["data"] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                d["data"] = None
        out.append(d)
    return out


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str) -> dict:
    """Get an artifact by ID."""
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact
