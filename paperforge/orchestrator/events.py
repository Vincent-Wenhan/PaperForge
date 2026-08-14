"""SSE event emitter and event manager.

The EventManager keeps per-run subscriber queues. The EventEmitter
is what orchestrator code uses to broadcast events to all subscribers.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any, Protocol

from paperforge.llm.base import ToolCall


class Event:
    """An event to be sent to subscribers."""

    __slots__ = ("id", "type", "data", "run_id", "task_id", "ts", "seq")

    def __init__(
        self,
        type: str,
        data: Any = None,
        run_id: str | None = None,
        ts: float | None = None,
        id: str | None = None,
        seq: int = 0,
        task_id: str | None = None,
    ) -> None:
        self.id = id or f"evt_{uuid.uuid4().hex[:10]}"
        self.type = type
        self.data = data
        self.run_id = run_id
        self.task_id = task_id
        self.ts = ts or time.time()
        self.seq = seq


class EventEmitter:
    """Emitter for a single run. Holds a reference to the manager.

    A default ``task_id`` can be bound at construction time so the
    convenience wrappers below attach the current task unless overridden.
    """

    def __init__(
        self,
        run_id: str,
        manager: EventManager,
        task_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.manager = manager
        self.task_id = task_id

    async def emit(
        self,
        event_type: str,
        data: Any = None,
        task_id: str | None = None,
    ) -> Event:
        resolved_task_id = task_id if task_id is not None else self.task_id
        event = Event(
            type=event_type,
            data=data,
            run_id=self.run_id,
            task_id=resolved_task_id,
        )
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

    async def artifact_updated(self, artifact_id: str, data: dict[str, Any]) -> None:
        await self.emit(
            "artifact.updated",
            {"artifact_id": artifact_id, "data": data},
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

    async def task_created(self, task: dict[str, Any]) -> None:
        await self.emit(
            "task.created",
            {"task": task},
            task_id=task.get("id") or task.get("task_id"),
        )

    async def task_updated(self, task: dict[str, Any]) -> None:
        await self.emit(
            "task.updated",
            {"task": task},
            task_id=task.get("id") or task.get("task_id"),
        )

    async def task_completed(self, task: dict[str, Any]) -> None:
        await self.emit(
            "task.completed",
            {"task": task},
            task_id=task.get("id") or task.get("task_id"),
        )

    async def task_failed(self, task: dict[str, Any]) -> None:
        await self.emit(
            "task.failed",
            {"task": task},
            task_id=task.get("id") or task.get("task_id"),
        )

    async def task_cancelled(self, task: dict[str, Any]) -> None:
        await self.emit(
            "task.cancelled",
            {"task": task},
            task_id=task.get("id") or task.get("task_id"),
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
            task_id=task_id,
        )

    async def build_log_delta(self, step_id: str, text: str) -> None:
        """Stream a build/lint log line in-band."""
        await self.emit("build.log.delta", {"step_id": step_id, "text": text})

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

    async def run_updated(self, **data: Any) -> None:
        """Broadcast a durable run metadata update (title/phase/status)."""
        await self.emit("run.updated", {"run_id": self.run_id, **data})


class EventManager:
    """Persist-then-fan-out event manager.

    Owns the authoritative seq (assigned by the store) and delegates
    fan-out to an injected EventBroker. SSE clients subscribe
    through the broker; swapping InProcessEventBroker for RedisBroker in
    production requires no business-layer change.
    """

    def __init__(
        self,
        storage: Any | None = None,
        broker: EventBroker | None = None,
    ) -> None:
        self._history: dict[str, list[Event]] = defaultdict(list)
        self._max_history = 1000
        self._storage = storage
        self._broker = broker or InProcessEventBroker()

    def register(self, run_id: str) -> asyncio.Queue:
        return self._broker.subscribe(run_id)

    def unregister(self, run_id: str, queue: asyncio.Queue) -> None:
        if hasattr(self._broker, "unsubscribe"):
            self._broker.unsubscribe(run_id, queue)  # type: ignore[attr-defined]

    async def broadcast(self, event: Event) -> None:
        rid = event.run_id or ""

        # Persist first so DB seq is authoritative; on failure, stop pretending
        # to be a durable stream (raiding an in-memory seq would let the browser
        # see seq=N that never reaches the DB).
        try:
            storage = self._storage
            if storage is None:
                from paperforge.storage.db import get_storage

                storage = get_storage()
            persist_start = time.monotonic()
            row = await asyncio.to_thread(
                storage.append_run_event,
                run_id=rid,
                event_id=event.id,
                event_type=event.type,
                data=event.data,
                task_id=event.task_id,
            )
            event.seq = row["seq"]
            try:
                from paperforge.observability.metrics import get_metrics

                get_metrics().record_duration(
                    "event_persist_ms",
                    time.monotonic() - persist_start,
                )
            except Exception:
                pass
        except Exception:
            raise EventPersistenceError(rid, event.id) from None

        self._history[rid].append(event)
        if len(self._history[rid]) > self._max_history:
            self._history[rid].pop(0)

        await self._broker.publish(event)

    def get_history(self, run_id: str) -> list[Event]:
        try:
            storage = self._storage
            if storage is None:
                from paperforge.storage.db import get_storage

                storage = get_storage()
            rows = storage.list_run_events(run_id, after_seq=0)
            if rows:
                return [
                    Event(
                        type=row["type"],
                        data=row.get("data"),
                        run_id=run_id,
                        id=row["id"],
                        seq=int(row["seq"]),
                        task_id=row.get("task_id"),
                    )
                    for row in rows
                ]
        except Exception:
            pass
        return list(self._history.get(run_id, []))

    def has_subscribers(self, run_id: str) -> bool:
        subscribers = getattr(self._broker, "subscribers", None)
        return bool(subscribers and subscribers(run_id))


class EventPersistenceError(Exception):
    """Raised when an event cannot be persisted durably.

    The SSE connection is dropped and the client recovers via snapshot +
    cursor rather than a fabricated in-memory seq.
    """

    def __init__(self, run_id: str, event_id: str) -> None:
        self.run_id = run_id
        self.event_id = event_id
        super().__init__(f"Event persistence failed for run={run_id} event={event_id}")



class EventStore(Protocol):
    """Durable event persistence."""

    def append(self, event: Event) -> Event:
        ...

    def list_after(self, run_id: str, seq: int) -> list[Event]:
        ...


class EventBroker(Protocol):
    """In-memory fan-out of events to subscribers."""

    async def publish(self, event: Event) -> None:
        ...

    def subscribe(self, run_id: str) -> asyncio.Queue[Event]:
        ...


class InProcessEventBroker(EventBroker):
    """Single-process broker. Redis/Postgres impls can be added later if needed."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = defaultdict(list)

    async def publish(self, event: Event) -> None:
        for queue in self._subscribers[event.run_id or ""]:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Dropping a live event is recoverable (seq gap triggers snapshot
                # hydration) but must stay observable so broker backpressure is
                # visible rather than surfacing only as occasional hydrates.
                from paperforge.observability.metrics import get_metrics

                get_metrics().increment("broker_live_drop_total")

    def subscribe(self, run_id: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[Event]) -> None:
        if queue in self._subscribers.get(run_id, []):
            self._subscribers[run_id].remove(queue)

    def subscribers(self, run_id: str) -> list[asyncio.Queue[Event]]:
        return list(self._subscribers.get(run_id, []))


_event_manager: EventManager | None = None


def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager


def reset_event_manager() -> None:
    global _event_manager
    _event_manager = None
