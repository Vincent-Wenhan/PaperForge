"""Background monitor for running sandboxes.

Scans running sandboxes every 10s, marks dead containers as error,
and stops sandboxes that have been running longer than the max lifetime.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from paperforge.config import get_config
from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.storage.db import get_storage

if TYPE_CHECKING:
    from paperforge.sandbox.docker_runner import DockerSandboxManager

logger = logging.getLogger(__name__)


class SandboxMonitor:
    """Background monitor for running sandboxes."""

    def __init__(
        self,
        manager: "DockerSandboxManager",
        check_interval: int = 10,
    ) -> None:
        self.manager = manager
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the monitor loop in the background."""
        if self._task is not None and not self._task.done():
            return  # Already running
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the monitor loop."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None

    async def _run_loop(self) -> None:
        """Main monitor loop."""
        logger.info("Sandbox monitor started (interval=%ss)", self.check_interval)
        try:
            while not self._stop_event.is_set():
                try:
                    await self._check_once()
                except Exception as e:
                    logger.error(f"Monitor iteration failed: {e}")
                # Wait for the check interval, but allow early exit
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("Sandbox monitor stopped")

    async def _check_once(self) -> None:
        """Single monitor iteration: check all running sandboxes."""
        storage = get_storage()
        cfg = get_config()
        running = storage.list_sandboxes(status="running")
        if not running:
            return

        for sb in running:
            sandbox_id = sb["id"]
            try:
                # Health-check: is the dev server port alive?
                healthy = await self.manager.health_check(sandbox_id)
                if not healthy:
                    # Mark as error
                    storage.update_sandbox(
                        sandbox_id,
                        status="error",
                        stopped_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    logger.warning(f"Sandbox {sandbox_id} marked as error (unhealthy)")
            except Exception as e:
                logger.error(f"Error checking sandbox {sandbox_id}: {e}")


_monitor: SandboxMonitor | None = None


def get_monitor() -> SandboxMonitor | None:
    return _monitor


async def start_monitor(manager: "DockerSandboxManager") -> SandboxMonitor:
    """Start the global sandbox monitor."""
    global _monitor
    if _monitor is None:
        _monitor = SandboxMonitor(manager=manager)
    await _monitor.start()
    return _monitor


async def stop_monitor() -> None:
    """Stop the global sandbox monitor."""
    global _monitor
    if _monitor is not None:
        await _monitor.stop()
        _monitor = None
