"""App-based file API routes (doc 8.4).

These endpoints operate on a generated Next.js app identified by its
artifact_id (the app artifact stored when `generate_nextjs_app` runs).
They allow file management even when no sandbox is currently running.
"""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()

ALLOWED_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".json", ".css", ".md", ".txt",
    ".html", ".svg",
}
BLOCKED_PARTS = {"node_modules", ".next", ".git", "dist", "build", ".cache"}
MAX_FILE_SIZE = 1_000_000


class FileWrite(BaseModel):
    content: str


class FileCreate(BaseModel):
    type: str  # "file" or "directory"
    path: str
    content: str = ""


class FilePatch(BaseModel):
    new_path: str


def _get_app_path(app_id: str, run_id: str | None = None) -> Path:
    """Resolve the app artifact's filesystem path."""
    storage = get_storage()
    artifact = storage.get_artifact(app_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="App artifact not found")
    if artifact.get("type") != "nextjs_app":
        raise HTTPException(status_code=400, detail="Artifact is not a Next.js app")
    if run_id is not None and artifact.get("run_id") != run_id:
        raise HTTPException(status_code=403, detail="App artifact does not belong to this run")

    metadata = artifact.get("metadata") or {}
    app_path = metadata.get("app_path")
    if not app_path:
        raise HTTPException(status_code=500, detail="App artifact missing app_path metadata")

    p = Path(app_path).resolve()
    try:
        p.relative_to(storage.apps_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="App path is outside the server workspace") from exc
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="App directory not found on disk")
    return p


def _resolve_safe(app_path: Path, file_path: str) -> Path:
    if not file_path:
        raise HTTPException(status_code=400, detail="Empty file path")

    base = app_path.resolve()
    full_path = (base / file_path).resolve()

    try:
        full_path.relative_to(base)
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path outside app") from None

    if any(part in BLOCKED_PARTS for part in full_path.parts):
        raise HTTPException(status_code=403, detail="Blocked path segment")

    return full_path


def _resolve_safe_file(app_path: Path, file_path: str) -> Path:
    full_path = _resolve_safe(app_path, file_path)
    if full_path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=403,
            detail=f"Unsupported file type: {full_path.suffix or '(none)'}",
        )
    return full_path


def _ensure_content_size(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")


def _record_revision(
    app_id: str,
    app_path: Path,
    source: str = "user_edit",
) -> dict:
    storage = get_storage()
    artifact = storage.get_artifact(app_id)
    if not artifact:
        return {}
    try:
        return storage.create_workspace_revision(
            run_id=artifact["run_id"],
            app_id=app_id,
            source=source,
            app_path=app_path,
        )
    except OSError:
        return {}


@router.get("/{app_id}/revisions")
async def list_revisions(app_id: str, run_id: str | None = None) -> dict:
    _get_app_path(app_id, run_id)
    return {"revisions": get_storage().list_workspace_revisions(app_id)}


@router.get("/{app_id}/revisions/{revision_id}")
async def get_revision(
    app_id: str,
    revision_id: str,
    run_id: str | None = None,
) -> dict:
    _get_app_path(app_id, run_id)
    revision = get_storage().get_workspace_revision(revision_id, include_snapshot=True)
    if not revision or revision.get("app_id") != app_id:
        raise HTTPException(status_code=404, detail="Workspace revision not found")
    parent = (
        get_storage().get_workspace_revision(revision["parent_revision_id"], include_snapshot=True)
        if revision.get("parent_revision_id")
        else None
    )
    before = (parent or {}).get("snapshot") or {}
    after = revision.get("snapshot") or {}
    revision["files"] = [
        {
            "path": path,
            "before": before.get(path),
            "after": after.get(path),
        }
        for path in revision.get("changed_files", [])
    ]
    revision.pop("snapshot", None)
    return revision


@router.post("/{app_id}/revisions/{revision_id}/restore")
async def restore_revision(
    app_id: str,
    revision_id: str,
    run_id: str | None = None,
) -> dict:
    app_path = _get_app_path(app_id, run_id)
    storage = get_storage()
    revision = storage.get_workspace_revision(revision_id, include_snapshot=True)
    if not revision or revision.get("app_id") != app_id:
        raise HTTPException(status_code=404, detail="Workspace revision not found")
    if run_id is not None and revision.get("run_id") != run_id:
        raise HTTPException(status_code=403, detail="Workspace revision does not belong to this run")

    try:
        storage.restore_workspace_revision(revision_id, app_path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"Could not restore workspace revision: {exc}") from exc

    restored = _record_revision(app_id, app_path, source="restore")
    return {
        "restored": True,
        "source_revision_id": revision_id,
        "revision_id": restored.get("id"),
    }


@router.get("/{app_id}/tree")
async def get_tree(app_id: str, run_id: str | None = None) -> dict:
    app_path = _get_app_path(app_id, run_id)
    tree: list[dict] = []

    for path in sorted(app_path.rglob("*")):
        if not path.exists():
            continue
        rel_parts = path.relative_to(app_path).parts
        if any(part in BLOCKED_PARTS for part in rel_parts):
            continue
        if path.is_file() and path.suffix.lower() not in ALLOWED_EXTS:
            continue
        rel_path = "/".join(rel_parts)
        tree.append({
            "path": rel_path,
            "type": "directory" if path.is_dir() else "file",
            "size": path.stat().st_size if path.is_file() else 0,
        })

    return {"tree": tree}


@router.get("/{app_id}/files/{file_path:path}")
async def read_file(app_id: str, file_path: str, run_id: str | None = None) -> dict:
    app_path = _get_app_path(app_id, run_id)
    full_path = _resolve_safe_file(app_path, file_path)

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if full_path.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    return {"path": file_path, "content": full_path.read_text(encoding="utf-8")}


@router.put("/{app_id}/files/{file_path:path}")
async def write_file(
    app_id: str,
    file_path: str,
    req: FileWrite,
    run_id: str | None = None,
) -> dict:
    app_path = _get_app_path(app_id, run_id)
    full_path = _resolve_safe_file(app_path, file_path)
    _ensure_content_size(req.content)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
    revision = _record_revision(app_id, app_path)
    return {"path": file_path, "saved": True, "revision_id": revision.get("id")}


@router.post("/{app_id}/entries")
async def create_entry(
    app_id: str,
    req: FileCreate,
    run_id: str | None = None,
) -> dict:
    app_path = _get_app_path(app_id, run_id)
    if req.type not in {"file", "directory"}:
        raise HTTPException(status_code=400, detail="Entry type must be file or directory")
    full_path = _resolve_safe(app_path, req.path)

    if req.type == "directory":
        if full_path.exists():
            raise HTTPException(status_code=409, detail="Entry already exists")
        full_path.mkdir(parents=True, exist_ok=False)
    else:
        if full_path.exists():
            raise HTTPException(status_code=409, detail="Entry already exists")
        if full_path.suffix.lower() not in ALLOWED_EXTS:
            raise HTTPException(status_code=403, detail=f"Unsupported file type: {full_path.suffix or '(none)'}")
        _ensure_content_size(req.content)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(req.content, encoding="utf-8")

    revision = _record_revision(app_id, app_path)
    return {"path": req.path, "created": True, "revision_id": revision.get("id")}


@router.patch("/{app_id}/entries/{file_path:path}")
async def rename_entry(
    app_id: str,
    file_path: str,
    req: FilePatch,
    run_id: str | None = None,
) -> dict:
    app_path = _get_app_path(app_id, run_id)
    src = _resolve_safe(app_path, file_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    new_path = _resolve_safe(app_path, req.new_path)
    if src.is_file() and new_path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(status_code=403, detail=f"Unsupported file type: {new_path.suffix or '(none)'}")
    if new_path.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(new_path))
    revision = _record_revision(app_id, app_path)
    return {"path": str(new_path), "renamed": True, "revision_id": revision.get("id")}


@router.delete("/{app_id}/entries/{file_path:path}")
async def delete_entry(app_id: str, file_path: str, run_id: str | None = None) -> dict:
    app_path = _get_app_path(app_id, run_id)
    full_path = _resolve_safe(app_path, file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if full_path.is_dir():
        shutil.rmtree(full_path)
    else:
        full_path.unlink()
    revision = _record_revision(app_id, app_path)
    return {"path": file_path, "deleted": True, "revision_id": revision.get("id")}


@router.get("/{app_id}/download")
async def download_zip(app_id: str, run_id: str | None = None) -> StreamingResponse:
    app_path = _get_app_path(app_id, run_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in app_path.rglob("*"):
            if not path.exists() or not path.is_file():
                continue
            rel_parts = path.relative_to(app_path).parts
            if any(part in BLOCKED_PARTS for part in rel_parts):
                continue
            if path.suffix.lower() not in ALLOWED_EXTS:
                continue
            arcname = "/".join(rel_parts)
            zf.write(path, arcname)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={app_id}.zip"},
    )
