"""RunTaskManager: tracks orchestrator background tasks per run.

Supports cancellation and cleanup on app shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta

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


class RunQueue:
    """Serializes orchestrator executions per run, so follow-up messages can be
    queued or interrupt the running task instead of being rejected with 409.

    The DB `tasks` table is the source of truth; this queue is only the
    in-process executor that drains queued tasks for a run.
    """

    def __init__(self, storage=None) -> None:
        self._queues: dict[str, asyncio.Queue[tuple[str, Coroutine]]] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._manager = get_run_task_manager()
        self._storage = storage

    async def enqueue(self, run_id: str, task_id: str, coro: Coroutine) -> None:
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue()
        await self._queues[run_id].put((task_id, coro))

        worker = self._workers.get(run_id)
        if worker is None or worker.done():
            self._workers[run_id] = asyncio.create_task(self._worker(run_id))

    async def _worker(self, run_id: str) -> None:
        queue = self._queues.get(run_id)
        storage = self._storage or _default_storage()
        try:
            while queue is not None and not queue.empty():
                task_id, coro = await queue.get()
                started_at = asyncio.get_event_loop().time()
                executed = await self._claim_and_run(run_id, task_id, coro, storage)
                if executed:
                    try:
                        from paperforge.observability.metrics import get_metrics

                        get_metrics().record_duration(
                            "task_duration_ms",
                            asyncio.get_event_loop().time() - started_at,
                        )
                    except Exception:
                        pass
                if not executed and storage is not None:
                    storage.update_task(task_id=task_id, status="queued")
                queue.task_done()
        finally:
            self._queues.pop(run_id, None)
            self._workers.pop(run_id, None)

    async def _claim_and_run(self, run_id, task_id, coro, storage):
        """Claim the DB task with a lease, run it while renewing the lease, and
        release on completion so a restart can reclaim stale running rows."""
        if storage is None:
            return False
        from paperforge.config import get_config
        from datetime import timedelta

        cfg = get_config()
        worker_id = cfg.WORKER_ID
        lease_until = datetime.utcnow() + timedelta(seconds=cfg.WORKER_LEASE_SECONDS)
        claimed = storage.claim_next_task(
            worker_id=worker_id,
            lease_until=lease_until.isoformat(),
        )
        if not claimed or claimed["id"] != task_id:
            return False

        # Renew the lease on a heartbeat while the task runs (doc 37.2).
        heartbeat = asyncio.create_task(
            self._heartbeat(
                task_id,
                worker_id,
                interval=cfg.WORKER_HEARTBEAT_SECONDS,
                lease_seconds=cfg.WORKER_LEASE_SECONDS,
                storage=storage,
            )
        )
        self._manager.start(run_id, coro)
        task = self._manager.tasks.get(run_id)
        try:
            if task is not None:
                await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Task %s for run %s failed", task_id, run_id)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass
            if storage is not None:
                row = storage.get_task(task_id)
                status = row["status"] if row else "failed"
                if status == "running":
                    storage.update_task(task_id=task_id, status="completed")
        return True

    async def _heartbeat(self, task_id, worker_id, *, interval, lease_seconds, storage):
        while True:
            await asyncio.sleep(interval)
            lease_until = (datetime.utcnow() + timedelta(seconds=lease_seconds)).isoformat()
            ok = storage.renew_task_lease(
                task_id=task_id,
                worker_id=worker_id,
                lease_until=lease_until,
            )
            if not ok:
                # We lost the lease — stop renewing; the worker will give up.
                return

    def running(self, run_id: str) -> bool:
        return self._manager.is_running(run_id) or bool(self._queues.get(run_id))

    async def cancel_and_wait(self, run_id: str) -> bool:
        return await self._manager.cancel_and_wait(run_id)


def _default_storage():
    """Lazy import to avoid a circular import at module load."""
    try:
        from paperforge.storage.db import get_storage

        return get_storage()
    except Exception:
        return None

