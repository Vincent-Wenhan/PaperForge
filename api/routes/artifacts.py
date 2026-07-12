"""Artifacts API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()


class ArtifactUpdate(BaseModel):
    display_name: str | None = None


def _load_artifact_data(row: dict) -> dict:
    path = Path(row.get("path") or "")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


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
        d["data"] = _load_artifact_data(d)
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


@router.patch("/{artifact_id}")
async def update_artifact(artifact_id: str, req: ArtifactUpdate) -> dict:
    """Update an artifact's display name (or other editable fields)."""
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if req.display_name is not None:
        # Store display_name in the artifact metadata for now.
        meta = artifact.get("metadata") or {}
        meta["display_name"] = req.display_name
        # Write back to DB
        with storage._lock, storage._conn() as conn:
            conn.execute(
                "UPDATE artifacts SET metadata = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), artifact_id),
            )
        artifact["metadata"] = meta

    return storage.get_artifact(artifact_id)


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str) -> dict:
    """Delete an artifact by ID. Removes both DB row and JSON file."""
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Delete the JSON file if it exists
    path = Path(artifact.get("path") or "")
    if path.exists():
        path.unlink()

    # Delete the DB row
    with storage._lock, storage._conn() as conn:
        conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

    return {"status": "deleted", "artifact_id": artifact_id}


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """Download an artifact as a JSON file."""
    storage = get_storage()
    artifact = storage.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path = Path(artifact.get("path") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=f"{artifact_id}.json",
    )
