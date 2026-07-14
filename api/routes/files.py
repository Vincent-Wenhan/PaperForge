"""Files API routes: read/write/list/create/rename/move/delete files."""

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


def _resolve_safe(sandbox: dict, file_path: str) -> Path:
    if not file_path:
        raise HTTPException(status_code=400, detail="Empty file path")

    base = Path(sandbox["app_path"]).resolve()
    full_path = (base / file_path).resolve()

    try:
        full_path.relative_to(base)
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path outside sandbox") from None

    if any(part in BLOCKED_PARTS for part in full_path.parts):
        raise HTTPException(status_code=403, detail="Blocked path segment")

    return full_path


def _resolve_safe_file(sandbox: dict, file_path: str) -> Path:
    full_path = _resolve_safe(sandbox, file_path)
    if full_path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=403,
            detail=f"Unsupported file type: {full_path.suffix or '(none)'}",
        )
    return full_path


def _ensure_content_size(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")


@router.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(sandbox_id: str, file_path: str) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe_file(sandbox, file_path)

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if full_path.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    return {"path": file_path, "content": full_path.read_text(encoding="utf-8")}


@router.put("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def write_file(sandbox_id: str, file_path: str, req: FileWrite) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe_file(sandbox, file_path)
    _ensure_content_size(req.content)

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
    return {"path": file_path, "saved": True}


@router.post("/sandboxes/{sandbox_id}/entries")
async def create_entry(sandbox_id: str, req: FileCreate) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if req.type not in {"file", "directory"}:
        raise HTTPException(status_code=400, detail="Entry type must be file or directory")

    full_path = _resolve_safe(sandbox, req.path)
    if full_path.exists():
        raise HTTPException(status_code=409, detail="Entry already exists")

    if req.type == "directory":
        full_path.mkdir(parents=True, exist_ok=False)
    else:
        if full_path.suffix.lower() not in ALLOWED_EXTS:
            raise HTTPException(
                status_code=403,
                detail=f"Unsupported file type: {full_path.suffix or '(none)'}",
            )
        _ensure_content_size(req.content)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(req.content, encoding="utf-8")

    return {"path": req.path, "created": True}


@router.patch("/sandboxes/{sandbox_id}/entries/{file_path:path}")
async def rename_entry(
    sandbox_id: str,
    file_path: str,
    req: FilePatch,
) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    src = _resolve_safe(sandbox, file_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    new_path = _resolve_safe(sandbox, req.new_path)
    if src.is_file() and new_path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=403,
            detail=f"Unsupported file type: {new_path.suffix or '(none)'}",
        )
    if new_path.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(new_path))
    return {"path": str(new_path), "renamed": True}


@router.delete("/sandboxes/{sandbox_id}/entries/{file_path:path}")
async def delete_entry(sandbox_id: str, file_path: str) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe(sandbox, file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Not found")

    if full_path.is_dir():
        shutil.rmtree(full_path)
    else:
        full_path.unlink()
    return {"path": file_path, "deleted": True}


@router.get("/sandboxes/{sandbox_id}/tree")
async def get_file_tree(sandbox_id: str) -> dict:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    root = Path(sandbox["app_path"])
    if not root.exists():
        return {"tree": []}

    tree: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.exists():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in BLOCKED_PARTS for part in rel_parts):
            continue
        if path.is_file() and path.suffix.lower() not in ALLOWED_EXTS:
            continue
        rel_path = "/".join(rel_parts)
        tree.append(
            {
                "path": rel_path,
                "type": "directory" if path.is_dir() else "file",
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )

    return {"tree": tree}


@router.get("/sandboxes/{sandbox_id}/download")
async def download_sandbox_zip(sandbox_id: str) -> StreamingResponse:
    """Download the entire sandbox app as a ZIP file."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    root = Path(sandbox["app_path"])
    if not root.exists():
        raise HTTPException(status_code=404, detail="App path not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if not path.exists() or not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
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
        headers={"Content-Disposition": f"attachment; filename={sandbox_id}.zip"},
    )


@router.get("/sandboxes/{sandbox_id}/files/{file_path:path}/download")
async def download_single_file(sandbox_id: str, file_path: str) -> StreamingResponse:
    """Download a single file from a sandbox (doc 8.4)."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe_file(sandbox, file_path)
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if full_path.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    return StreamingResponse(
        io.BytesIO(full_path.read_bytes()),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={full_path.name}",
        },
    )
