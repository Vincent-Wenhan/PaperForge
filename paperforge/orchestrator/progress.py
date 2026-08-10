"""ProgressReporter: creates and updates Steps for a task (doc 13.2).

Emits step.started / step.progress / step.completed / step.failed so the
frontend conversation timeline can show live per-step activity.
"""

from __future__ import annotations

from typing import Any

from paperforge.orchestrator.events import EventEmitter
from paperforge.storage.db import Storage


class ProgressReporter:
    def __init__(
        self,
        run_id: str,
        task_id: str,
        storage: Storage,
        emit: EventEmitter,
    ) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.storage = storage
        self.emit = emit

    async def start(
        self,
        *,
        kind: str,
        title: str,
        metadata: dict | None = None,
    ) -> str:
        step = self.storage.create_step(
            task_id=self.task_id,
            run_id=self.run_id,
            kind=kind,
            title=title,
            status="running",
            metadata=metadata,
        )
        await self.emit.emit(
            "step.started",
            {
                "step_id": step["id"],
                "kind": kind,
                "title": title,
                "metadata": metadata or {},
            },
            task_id=self.task_id,
        )
        return step["id"]

    async def progress(
        self,
        step_id: str,
        *,
        percent: float | None = None,
        detail: str | None = None,
    ) -> None:
        await self.emit.emit(
            "step.progress",
            {"step_id": step_id, "percent": percent, "detail": detail},
            task_id=self.task_id,
        )

    async def complete(
        self,
        step_id: str,
        *,
        summary: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.storage.complete_step(step_id, summary=summary)
        await self.emit.emit(
            "step.completed",
            {"step_id": step_id, "summary": summary, "metadata": metadata or {}},
            task_id=self.task_id,
        )

    async def fail(
        self,
        step_id: str,
        *,
        error: str | None = None,
    ) -> None:
        self.storage.fail_step(step_id, error=error)
        await self.emit.emit(
            "step.failed",
            {"step_id": step_id, "error": error},
            task_id=self.task_id,
        )
