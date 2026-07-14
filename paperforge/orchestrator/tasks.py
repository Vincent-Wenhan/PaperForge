"""RunTaskManager: tracks orchestrator background tasks per run.

Supports cancellation and cleanup on app shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)


class RunTaskManager:
    """Tracks asyncio.Tasks for orchestrator runs, keyed by run_id."""

    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self, run_id: str, coro: Coroutine) -> asyncio.Task:
        """Start a background task for a run. Replaces any existing task."""
        existing = self.tasks.get(run_id)
        if existing and not existing.done():
            existing.cancel()

        task = asyncio.create_task(coro)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return task

    def cancel(self, run_id: str) -> bool:
        """Cancel a running task. Returns True if a task was cancelled."""
        task = self.tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def cancel_and_wait(self, run_id: str, timeout: float = 5.0) -> bool:
        """Cancel a run and wait briefly for its coroutine to drain.

        The synchronous ``cancel`` method remains for compatibility with
        older callers. API cancellation uses this bounded variant so a task
        cannot continue mutating a run after its status is persisted.
        """
        task = self.tasks.get(run_id)
        if task is None or task.done():
            return False

        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.CancelledError:
            pass
        except TimeoutError:
            logger.warning("Timed out waiting for run task %s to cancel", run_id)
        except Exception:
            logger.exception("Run task %s failed while cancelling", run_id)
        finally:
            if task.done() and self.tasks.get(run_id) is task:
                self.tasks.pop(run_id, None)
        return True

    def is_running(self, run_id: str) -> bool:
        """Check if a run has an active task."""
        task = self.tasks.get(run_id)
        return task is not None and not task.done()

    async def cancel_all(self) -> None:
        """Cancel all running tasks. Called on app shutdown."""
        for task in list(self.tasks.values()):
            if not task.done():
                task.cancel()
        for task in list(self.tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.tasks.clear()


_run_task_manager: RunTaskManager | None = None


def get_run_task_manager() -> RunTaskManager:
    global _run_task_manager
    if _run_task_manager is None:
        _run_task_manager = RunTaskManager()
    return _run_task_manager


def reset_run_task_manager() -> None:
    global _run_task_manager
    _run_task_manager = None
