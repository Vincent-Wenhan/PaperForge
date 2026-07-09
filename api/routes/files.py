"""Files API routes: read/write/list files in a sandbox or generated app."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()

# ponytail: file interface safety — explicit allow-list keeps the editor
# out of binaries, lockfiles, and build artifacts.
ALLOWED_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".json", ".css", ".md", ".txt",
    ".html", ".svg",
}
BLOCKED_PARTS = {"node_modules", ".next", ".git", "dist", "build", ".cache"}
MAX_FILE_SIZE = 1_000_000  # 1 MB


class FileWrite(BaseModel):
    content: str


def _resolve_safe(sandbox: dict, file_path: str) -> Path:
    """Resolve a sandbox-relative path, rejecting traversal and blocked dirs."""
    if not file_path:
        raise HTTPException(status_code=400, detail="Empty file path")

    base = Path(sandbox["app_path"]).resolve()
    full_path = (base / file_path).resolve()

    try:
        full_path.relative_to(base)
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path outside sandbox")

    if any(part in BLOCKED_PARTS for part in full_path.parts):
        raise HTTPException(status_code=403, detail="Blocked path segment")

    if full_path.suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=403,
            detail=f"Unsupported file type: {full_path.suffix or '(none)'}",
        )

    return full_path


@router.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(sandbox_id: str, file_path: str) -> dict:
    """Read a file from the sandbox's app directory."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe(sandbox, file_path)

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if full_path.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    return {"path": file_path, "content": full_path.read_text(encoding="utf-8")}


@router.put("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def write_file(sandbox_id: str, file_path: str, req: FileWrite) -> dict:
    """Write content to a file in the sandbox's app directory."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    full_path = _resolve_safe(sandbox, file_path)

    if full_path.exists() and full_path.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

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
