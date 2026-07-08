"""Files API routes: read/write/list files in a sandbox or generated app."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()


class FileWrite(BaseModel):
    content: str


@router.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(sandbox_id: str, file_path: str) -> dict:
    """Read a file from the sandbox's app directory."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = Path(sandbox["app_path"]) / file_path

    # Path traversal check
    try:
        full_path.resolve().relative_to(Path(sandbox["app_path"]).resolve())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path outside sandbox")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return {"path": file_path, "content": full_path.read_text(encoding="utf-8")}


@router.put("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def write_file(sandbox_id: str, file_path: str, req: FileWrite) -> dict:
    """Write content to a file in the sandbox's app directory."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = Path(sandbox["app_path"]) / file_path

    # Path traversal check
    try:
        full_path.resolve().relative_to(Path(sandbox["app_path"]).resolve())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path outside sandbox")

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(req.content, encoding="utf-8")
    return {"path": file_path, "saved": True}


@router.get("/sandboxes/{sandbox_id}/tree")
async def get_file_tree(sandbox_id: str) -> dict:
    """Get the file tree for a sandbox's app directory."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    root = Path(sandbox["app_path"])
    if not root.exists():
        return {"tree": []}

    skip_dirs = {"node_modules", ".next", ".git", "dist", "build"}
    tree: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.exists():
            continue
        rel_path = str(path.relative_to(root)).replace("\\", "/")
        if any(part in skip_dirs for part in path.parts):
            continue
        tree.append(
            {
                "path": rel_path,
                "type": "directory" if path.is_dir() else "file",
                "size": path.stat().st_size if path.is_file() else 0,
            }
        )

    return {"tree": tree}
