"""Sandboxes API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.sandbox.docker_runner import DockerSandboxManager
from paperforge.storage.db import get_storage

router = APIRouter()


class SandboxStart(BaseModel):
    app_path: str
    run_id: str | None = None


@router.post("")
async def start_sandbox(req: SandboxStart) -> dict:
    """Start a new sandbox container."""
    storage = get_storage()
    manager = DockerSandboxManager(storage=storage)
    try:
        sandbox = await manager.start(run_id=req.run_id or "", app_path=req.app_path)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return sandbox


@router.get("")
async def list_sandboxes(status: str | None = None) -> list[dict]:
    """List all sandboxes."""
    storage = get_storage()
    return storage.list_sandboxes(status=status)


@router.get("/latest")
async def get_latest_sandbox(run_id: str) -> dict | None:
    """Get the most recent sandbox for a run (doc 1A.11).

    Used by the frontend during hydration to restore the active sandbox
    without relying on transient SSE events.
    """
    storage = get_storage()
    return storage.get_latest_sandbox_for_run(run_id)


@router.get("/{sandbox_id}")
async def get_sandbox(sandbox_id: str) -> dict:
    """Get a sandbox by ID."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return sandbox


@router.get("/{sandbox_id}/logs")
async def get_sandbox_logs(sandbox_id: str, tail: int = 200) -> dict:
    """Get container logs for a sandbox."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    manager = DockerSandboxManager(storage=storage)
    logs = await manager.get_logs(sandbox_id, tail=tail)
    return {"sandbox_id": sandbox_id, "logs": logs}


@router.post("/{sandbox_id}/stop")
async def stop_sandbox(sandbox_id: str) -> dict:
    """Stop a running sandbox."""
    storage = get_storage()
    manager = DockerSandboxManager(storage=storage)
    await manager.stop(sandbox_id)
    return {"sandbox_id": sandbox_id, "status": "stopped"}


@router.post("/{sandbox_id}/restart")
async def restart_sandbox(sandbox_id: str) -> dict:
    """Restart a sandbox."""
    storage = get_storage()
    manager = DockerSandboxManager(storage=storage)
    sandbox = await manager.restart(sandbox_id)
    return sandbox
