"""Sandboxes API routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_sandbox_manager_dep
from paperforge.sandbox.docker_runner import DockerSandboxManager
from paperforge.storage.db import get_storage

router = APIRouter()


class SandboxStart(BaseModel):
    app_artifact_id: str | None = None
    app_path: str | None = None
    run_id: str | None = None


def _resolve_app_path(req: SandboxStart) -> str:
    """Resolve an app artifact to a server-owned workspace path."""
    storage = get_storage()
    if req.app_artifact_id:
        artifact = storage.get_artifact(req.app_artifact_id)
        if not artifact or artifact.get("type") != "nextjs_app":
            raise HTTPException(status_code=404, detail="App artifact not found")
        if req.run_id and artifact.get("run_id") != req.run_id:
            raise HTTPException(status_code=403, detail="App artifact does not belong to this run")
        app_path = (artifact.get("metadata") or {}).get("app_path")
    else:
        app_path = req.app_path
        if app_path:
            if not req.run_id:
                raise HTTPException(status_code=422, detail="run_id is required with app_path")
            requested = Path(app_path).resolve()
            owned = False
            for artifact in storage.list_artifacts(run_id=req.run_id, artifact_type="nextjs_app"):
                metadata = artifact.get("metadata") or {}
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except json.JSONDecodeError:
                        metadata = {}
                if Path(metadata.get("app_path", "")).resolve() == requested:
                    owned = True
                    break
            if not owned:
                raise HTTPException(status_code=403, detail="App path is not owned by this run")

    if not app_path:
        raise HTTPException(status_code=422, detail="app_artifact_id is required")

    path = Path(app_path).resolve()
    try:
        path.relative_to(storage.apps_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="App path is outside the server workspace") from exc
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="App directory not found")
    return str(path)


@router.post("")
async def start_sandbox(
    req: SandboxStart,
    manager: DockerSandboxManager | None = Depends(get_sandbox_manager_dep),
) -> dict:
    """Start a new sandbox container."""
    if manager is None:
        raise HTTPException(status_code=503, detail="Docker sandbox is unavailable")
    app_path = _resolve_app_path(req)
    try:
        sandbox = await manager.start(run_id=req.run_id or "", app_path=app_path)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
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
async def get_sandbox_logs(
    sandbox_id: str,
    tail: int = 200,
    manager: DockerSandboxManager | None = Depends(get_sandbox_manager_dep),
) -> dict:
    """Get container logs for a sandbox."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if manager is None:
        raise HTTPException(status_code=503, detail="Docker sandbox is unavailable")
    logs = await manager.get_logs(sandbox_id, tail=tail)
    return {"sandbox_id": sandbox_id, "logs": logs}


@router.post("/{sandbox_id}/stop")
async def stop_sandbox(
    sandbox_id: str,
    manager: DockerSandboxManager | None = Depends(get_sandbox_manager_dep),
) -> dict:
    """Stop a running sandbox."""
    storage = get_storage()
    if not storage.get_sandbox(sandbox_id):
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if manager is None:
        raise HTTPException(status_code=503, detail="Docker sandbox is unavailable")
    try:
        await manager.stop(sandbox_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"sandbox_id": sandbox_id, "status": "stopped"}


@router.post("/{sandbox_id}/restart")
async def restart_sandbox(
    sandbox_id: str,
    manager: DockerSandboxManager | None = Depends(get_sandbox_manager_dep),
) -> dict:
    """Restart a sandbox."""
    storage = get_storage()
    if not storage.get_sandbox(sandbox_id):
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if manager is None:
        raise HTTPException(status_code=503, detail="Docker sandbox is unavailable")
    try:
        sandbox = await manager.restart(sandbox_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sandbox
