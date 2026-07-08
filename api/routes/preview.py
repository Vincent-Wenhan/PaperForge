"""Preview proxy route: forward requests to the sandbox's Next.js dev server."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from paperforge.storage.db import get_storage

router = APIRouter()


@router.get("/{sandbox_id}/{path:path}")
async def proxy_preview(sandbox_id: str, path: str, request: Request) -> Response:
    """Proxy a request to the sandbox's Next.js dev server."""
    storage = get_storage()
    sandbox = storage.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if sandbox.get("status") != "running":
        raise HTTPException(status_code=503, detail="Sandbox not running")

    port = sandbox.get("preview_port")
    if not port:
        raise HTTPException(status_code=503, detail="No preview port assigned")

    # Build target URL
    target_url = f"http://localhost:{port}/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    # Forward headers
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
    }

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            resp = await client.get(target_url, headers=headers)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Sandbox dev server not reachable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Sandbox dev server timed out")

    # Filter response headers
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
