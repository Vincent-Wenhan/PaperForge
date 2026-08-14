"""Central service for persisting and broadcasting task lifecycle transitions.

Every Task status/phase change that affects user-visible state goes through
``transition()`` so it is durable and broadcast exactly once, instead of each
call site doing storage.update_task + a bespoke emitter call. This keeps the
event contract consistent (task.created / task.updated / task.completed /
task.failed) and replayable.
"""

from __future__ import annotations

import asyncio
from typing import Any

from paperforge.orchestrator.events import EventEmitter
from paperforge.storage.db import Storage


class TaskLifecycleService:
    def __init__(self, storage: Storage, emitter: EventEmitter) -> None:
        self.storage = storage
        self.emitter = emitter

    async def transition(
        self,
        task_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """Persist a Task transition and broadcast it, returning the Task."""
        task = await asyncio.to_thread(
            self.storage.update_task,
            task_id=task_id,
            status=status,
            phase=phase,
        )
        if task is None:
            raise LookupError(f"Task not found: {task_id}")

        task_status = task.get("status")
        if task_status == "completed":
            await self.emitter.task_completed(task)
        elif task_status == "failed":
            await self.emitter.task_failed(task)
        elif task_status == "cancelled":
            await self.emitter.task_cancelled(task)
        else:
            await self.emitter.task_updated(task)
        return task

