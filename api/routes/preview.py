"""Preview proxy route: forward requests to the sandbox's Next.js dev server."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from paperforge.storage.db import get_storage

router = APIRouter()

FORWARDED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def _sandbox_target(sandbox_id: str) -> tuple[dict, int]:
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if sandbox.get("status") != "running":
        raise HTTPException(status_code=503, detail="Sandbox not running")
    port = sandbox.get("preview_port")
    if not port:
        raise HTTPException(status_code=503, detail="No preview port assigned")
    return sandbox, int(port)


@router.get("/status/{run_id}")
async def preview_status(run_id: str) -> dict:
    """Return durable preview state for run hydration."""
    storage = get_storage()
    sandbox = storage.get_latest_sandbox_for_run(run_id)
    if sandbox is None:
        return {"run_id": run_id, "status": "idle", "sandbox_id": None}

    status = sandbox.get("status")
    preview_status_value = sandbox.get("preview_status")
    if preview_status_value == "idle" and status in {"pending", "starting", "running"}:
        preview_status_value = "starting"
    elif preview_status_value == "idle" and status == "stopped":
        preview_status_value = "stopped"
    elif preview_status_value == "idle" and status in {"error", "failed"}:
        preview_status_value = "degraded"
    elif preview_status_value not in {"idle", "starting", "running", "degraded", "stopped", "error"}:
        if status == "running":
            preview_status_value = "starting"
        elif status in {"pending", "starting"}:
            preview_status_value = "starting"
        elif status in {"error", "failed"}:
            preview_status_value = "degraded"
        else:
            preview_status_value = "stopped"

    return {
        "run_id": run_id,
        "status": preview_status_value,
        "sandbox_id": sandbox.get("id"),
        "sandbox": sandbox,
        "preview_url": (
            sandbox.get("preview_url") or f"/api/preview/{sandbox['id']}/"
            if preview_status_value == "running"
            else None
        ),
        "error": sandbox.get("error"),
    }


@router.api_route(
    "/{sandbox_id}/{path:path}",
    methods=FORWARDED_METHODS,
)
async def proxy_preview(sandbox_id: str, path: str, request: Request) -> Response:
    """Proxy a request to the sandbox's Next.js dev server."""
    sandbox, port = _sandbox_target(sandbox_id)

    target_url = f"http://localhost:{port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
    }

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            resp = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body or None,
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Sandbox dev server not reachable") from None
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Sandbox dev server timed out") from None

    resp_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in ("content-length", "transfer-encoding", "connection")
    }

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
    )


@router.websocket("/{sandbox_id}/{path:path}")
async def proxy_preview_websocket(websocket: WebSocket, sandbox_id: str, path: str) -> None:
    """Relay Next.js HMR WebSocket frames through the preview prefix."""
    try:
        _sandbox, port = _sandbox_target(sandbox_id)
    except HTTPException as exc:
        await websocket.close(code=1013, reason=str(exc.detail))
        return

    query = f"?{websocket.query_params}" if websocket.query_params else ""
    target = f"ws://127.0.0.1:{port}/{path}{query}"
    await websocket.accept()

    try:
        async with websockets.connect(target, proxy=None) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            _done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (WebSocketDisconnect, websockets.WebSocketException, OSError):
        pass
    finally:
        for task in tasks if "tasks" in locals() else ():
            if not task.done():
                task.cancel()
        if websocket.client_state.value != "DISCONNECTED":
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()
