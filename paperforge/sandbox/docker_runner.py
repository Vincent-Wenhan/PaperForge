"""Docker sandbox manager.

Starts a Docker container per generated app, with:
- node:20-alpine image
- mounted app directory
- dynamic port allocation
- memory and CPU limits
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import docker
    from docker.errors import DockerException, NotFound
except ImportError:
    docker = None  # type: ignore

from paperforge.config import get_config
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def docker_available() -> bool:
    """Check if Docker is available and running."""
    if docker is None:
        return False
    try:
        client = docker.from_env()
        client.ping()
        return True
    except (DockerException, Exception):
        return False


class DockerSandboxManager:
    """Manages Docker-based sandboxes for generated Next.js apps."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self._client = None
        if docker_available():
            try:
                self._client = docker.from_env()
            except Exception:
                self._client = None

    async def start(self, run_id: str, app_path: str | Path) -> dict[str, Any]:
        """Start a new sandbox container.

        Args:
            run_id: associated run ID
            app_path: path to the generated Next.js app

        Returns:
            Sandbox dict with id, container_id, preview_port, etc.
        """
        app_path = Path(app_path).resolve()
        if not app_path.exists():
            raise FileNotFoundError(f"App path not found: {app_path}")

        cfg = get_config()

        # Enforce MAX_SANDBOXES limit
        running = self.storage.list_sandboxes(status="running")
        if len(running) >= cfg.MAX_SANDBOXES:
            raise RuntimeError(
                f"Maximum number of sandboxes reached ({cfg.MAX_SANDBOXES}). "
                "Stop an existing sandbox before starting a new one."
            )

        sandbox_id = f"sandbox_{uuid.uuid4().hex[:8]}"
        preview_port = find_free_port()

        image = cfg.SANDBOX_IMAGE
        mem_limit = cfg.SANDBOX_MEM_LIMIT
        cpu_quota = cfg.SANDBOX_CPU_QUOTA

        sandbox_record: dict[str, Any] = {
            "id": sandbox_id,
            "run_id": run_id,
            "container_id": None,
            "app_path": str(app_path),
            "preview_port": preview_port,
            "status": "pending",
        }

        # Save initial sandbox record
        self.storage.save_sandbox(**sandbox_record)

        # Check if Docker is available
        if not docker_available():
            logger.warning("Docker not available, sandbox will be in error state")
            self.storage.update_sandbox(
                sandbox_id,
                status="error",
            )
            sandbox_record["status"] = "error"
            return sandbox_record

        try:
            # Sandbox no longer runs install/build itself — that's the
            # BuildRunner's job (called by the verifier). The sandbox
            # assumes node_modules and .next/ are already present.
            container = self._client.containers.create(
                image=image,
                command="sh -c 'npm run dev -- --port 3000 --hostname 0.0.0.0'",
                volumes={str(app_path): {"bind": "/app", "mode": "rw"}},
                working_dir="/app",
                ports={"3000/tcp": preview_port},
                environment={
                    "NODE_ENV": "development",
                    "WATCHPACK_POLLING": "true",
                },
                detach=True,
                mem_limit=mem_limit,
                cpu_quota=cpu_quota,
                name=f"paperforge-{sandbox_id}",
            )

            container.start()
            container_id = container.id

            self.storage.update_sandbox(
                sandbox_id,
                container_id=container_id,
                status="running",
                started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )

            sandbox_record["container_id"] = container_id
            sandbox_record["status"] = "running"

            logger.info(
                f"Started sandbox {sandbox_id} (container {container_id[:12]}, port {preview_port})"
            )

            return sandbox_record

        except Exception as e:
            logger.error(f"Failed to start sandbox {sandbox_id}: {e}")
            self.storage.update_sandbox(sandbox_id, status="error")
            sandbox_record["status"] = "error"
            return sandbox_record

    async def stop(self, sandbox_id: str) -> dict[str, Any]:
        """Stop a running sandbox."""
        sandbox = self.storage.get_sandbox(sandbox_id)
        if not sandbox:
            raise ValueError(f"Sandbox not found: {sandbox_id}")

        if self._client and sandbox.get("container_id"):
            try:
                container = self._client.containers.get(sandbox["container_id"])
                container.stop(timeout=10)
                container.remove()
            except NotFound:
                logger.warning(f"Container not found: {sandbox['container_id']}")
            except Exception as e:
                logger.error(f"Error stopping container: {e}")

        self.storage.update_sandbox(
            sandbox_id,
            status="stopped",
            stopped_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        return {"sandbox_id": sandbox_id, "status": "stopped"}

    async def restart(self, sandbox_id: str) -> dict[str, Any]:
        """Restart a sandbox."""
        sandbox = self.storage.get_sandbox(sandbox_id)
        if not sandbox:
            raise ValueError(f"Sandbox not found: {sandbox_id}")

        await self.stop(sandbox_id)
        new_sandbox = await self.start(
            run_id=sandbox["run_id"],
            app_path=sandbox["app_path"],
        )
        return new_sandbox

    async def get_logs(self, sandbox_id: str, tail: int = 100) -> str:
        """Get container logs."""
        sandbox = self.storage.get_sandbox(sandbox_id)
        if not sandbox or not sandbox.get("container_id"):
            return ""

        if not self._client:
            return "[Docker not available]"

        try:
            container = self._client.containers.get(sandbox["container_id"])
            return container.logs(tail=tail).decode("utf-8", errors="replace")
        except Exception as e:
            return f"[Error getting logs: {e}]"

    async def health_check(self, sandbox_id: str) -> bool:
        """Check if the Next.js dev server is responding with HTTP 200."""
        sandbox = self.storage.get_sandbox(sandbox_id)
        if not sandbox or sandbox.get("status") != "running":
            return False

        port = sandbox.get("preview_port")
        if not port:
            return False

        try:
            import httpx
        except ImportError:
            # Fallback to TCP check if httpx not available
            try:
                reader, writer = await asyncio.open_connection("localhost", port)
                writer.close()
                await writer.wait_closed()
                return True
            except (ConnectionError, OSError):
                return False

        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                resp = await client.get(f"http://localhost:{port}/", timeout=2.0)
                return resp.status_code == 200
        except Exception:
            return False

    async def wait_for_ready(self, sandbox_id: str, timeout: int = 60) -> bool:
        """Wait for sandbox to be ready, polling health check."""
        start = time.time()
        while time.time() - start < timeout:
            if await self.health_check(sandbox_id):
                return True
            await asyncio.sleep(1)
        return False

    async def list_sandboxes(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.storage.list_sandboxes(status=status)

    async def shutdown_all(self) -> None:
        """Stop all running sandboxes. Called on app shutdown."""
        if not self._client:
            return

        running = self.storage.list_sandboxes(status="running")
        for sb in running:
            try:
                await self.stop(sb["id"])
            except Exception as e:
                logger.error(f"Error shutting down sandbox {sb['id']}: {e}")
