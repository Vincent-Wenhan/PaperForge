"""SSE event emitter and event manager.

The EventManager keeps per-run subscriber queues. The EventEmitter
is what orchestrator code uses to broadcast events to all subscribers.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any

from paperforge.llm.base import ToolCall


class Event:
    """An event to be sent to subscribers."""

    __slots__ = ("id", "type", "data", "run_id", "ts", "seq")

    def __init__(
        self,
        type: str,
        data: Any = None,
        run_id: str | None = None,
        ts: float | None = None,
        id: str | None = None,
        seq: int = 0,
    ) -> None:
        self.id = id or f"evt_{uuid.uuid4().hex[:10]}"
        self.type = type
        self.data = data
        self.run_id = run_id
        self.ts = ts or time.time()
        self.seq = seq


class EventEmitter:
    """Emitter for a single run. Holds a reference to the manager."""

    def __init__(self, run_id: str, manager: "EventManager") -> None:
        self.run_id = run_id
        self.manager = manager

    async def emit(self, event_type: str, data: Any = None) -> Event:
        event = Event(type=event_type, data=data, run_id=self.run_id)
        await self.manager.broadcast(event)
        return event

    # Convenience wrappers — each just calls emit() with the right type/payload.

    async def text(self, text: str) -> None:
        await self.emit("message.delta", {"text": text})

    async def message_started(self, message_id: str) -> None:
        await self.emit("message.started", {"message_id": message_id})

    async def message_delta(self, message_id: str, delta: str) -> None:
        await self.emit("message.delta", {"message_id": message_id, "delta": delta})

    async def message_completed(self, message_id: str, content: str) -> None:
        await self.emit("message.completed", {"message_id": message_id, "content": content})

    async def message_failed(self, message_id: str, error: str) -> None:
        await self.emit("message.failed", {"message_id": message_id, "error": error})

    async def tool_call(self, call: ToolCall) -> None:
        await self.emit(
            "tool.call",
            {"id": call.id, "name": call.name, "args": call.args},
        )

    async def tool_result(self, name: str, result: Any, call_id: str | None = None) -> None:
        await self.emit(
            "tool.result",
            {"name": name, "result": result, "call_id": call_id},
        )

    async def artifact_created(self, artifact_type: str, path: str, artifact_id: str) -> None:
        await self.emit(
            "artifact.created",
            {"type": artifact_type, "path": path, "artifact_id": artifact_id},
        )

    async def run_started(self) -> None:
        await self.emit("run.started", {"run_id": self.run_id})

    async def run_finished(self) -> None:
        await self.emit("run.finished", {"run_id": self.run_id})

    async def run_error(self, error: str) -> None:
        await self.emit("run.error", {"run_id": self.run_id, "error": error})

    async def approval_requested(self, approval_id: str, tool_name: str, args: dict[str, Any]) -> None:
        await self.emit(
            "approval.requested",
            {
                "approval_id": approval_id,
                "tool": tool_name,
                "args": args,
            },
        )

    async def approval_resolved(self, approval_id: str, approved: bool, tool_name: str) -> None:
        await self.emit(
            "approval.resolved",
            {
                "approval_id": approval_id,
                "tool": tool_name,
                "approved": approved,
            },
        )

    async def sandbox_started(self, sandbox_id: str, container_id: str, preview_port: int) -> None:
        await self.emit(
            "sandbox.started",
            {
                "sandbox_id": sandbox_id,
                "container_id": container_id,
                "preview_port": preview_port,
            },
        )

    async def sandbox_error(self, error: str, sandbox_id: str | None = None) -> None:
        await self.emit(
            "sandbox.error",
            {"sandbox_id": sandbox_id, "error": error},
        )

    async def preview_ready(self, sandbox_id: str, preview_url: str) -> None:
        await self.emit(
            "preview.ready",
            {"sandbox_id": sandbox_id, "preview_url": preview_url},
        )

    async def task_phase_changed(
        self,
        phase: str,
        previous_phase: str | None = None,
        task_id: str | None = None,
    ) -> None:
        await self.emit(
            "task.phase.changed",
            {
                "phase": phase,
                "previous_phase": previous_phase,
                "task_id": task_id,
            },
        )

    async def run_status_changed(
        self,
        status: str,
        previous_status: str | None = None,
    ) -> None:
        await self.emit(
            "run.status.changed",
            {
                "status": status,
                "previous_status": previous_status,
            },
        )


class EventManager:
    """Manages event subscribers per run, with monotonic seq per run."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[str, list[Event]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._max_history = 1000

    def register(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[run_id].append(q)
        return q

    def unregister(self, run_id: str, queue: asyncio.Queue) -> None:
        if queue in self._subscribers.get(run_id, []):
            self._subscribers[run_id].remove(queue)

    async def broadcast(self, event: Event) -> None:
        rid = event.run_id or ""
        # Assign monotonic seq per run.
        self._seq[rid] += 1
        event.seq = self._seq[rid]
        self._history[rid].append(event)
        if len(self._history[rid]) > self._max_history:
            self._history[rid].pop(0)
        for q in self._subscribers.get(rid, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def get_history(self, run_id: str) -> list[Event]:
        return list(self._history.get(run_id, []))

    def has_subscribers(self, run_id: str) -> bool:
        return bool(self._subscribers.get(run_id))


_event_manager: EventManager | None = None


def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager


def reset_event_manager() -> None:
    global _event_manager
    _event_manager = None
