"""PR-1 tests: atomic Message+Task creation, retry idempotency, lifecycle events."""

from __future__ import annotations

import asyncio

import pytest

from paperforge.orchestrator.events import EventEmitter, EventManager
from paperforge.orchestrator.task_lifecycle import TaskLifecycleService


@pytest.mark.asyncio
async def test_create_user_task_atomic_and_idempotent(storage):
    """Same public_id retry returns the SAME message+task, never a duplicate."""
    storage.create_run("run_atomic", "Atomic", status="active")

    a = storage.create_user_task(
        run_id="run_atomic", content="hello", public_id="client-1",
        phase="init", priority=0,
    )
    b = storage.create_user_task(
        run_id="run_atomic", content="hello", public_id="client-1",
        phase="init", priority=0,
    )

    # Same task and message on retry (idempotency), identical IDs.
    assert a.task["id"] == b.task["id"]
    assert a.message["id"] == b.message["id"]
    assert a.message["task_id"] == a.task["id"]

    # Exactly one message + one task in storage.
    msgs = storage.list_messages("run_atomic")
    assert len(msgs) == 1
    tasks = storage.list_tasks("run_atomic")
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_task_created_persists_by_seq(storage):
    """task.created emits and is durably persisted with a run-level seq."""
    storage.create_run("run_tc2", "TC", status="active")
    mgr = EventManager(storage=storage)
    emitter = EventEmitter(run_id="run_tc2", manager=mgr)

    task = storage.create_task(run_id="run_tc2", title="t", goal="g",
                               status="queued", phase="init")
    await emitter.task_created(task)

    history = mgr.get_history("run_tc2")
    assert len(history) == 1
    evt = history[0]
    assert evt.type == "task.created"
    assert evt.seq > 0
    assert evt.data["task"]["id"] == task["id"]
    assert evt.run_id == "run_tc2"


@pytest.mark.asyncio
async def test_lifecycle_broadcasts_updated_then_completed(storage):
    """transition() emits task.updated on progress, task.completed on terminal."""
    storage.create_run("run_lc", "LC", status="active")
    task = storage.create_task(run_id="run_lc", title="t", goal="g",
                               status="queued", phase="init")
    mgr = EventManager(storage=storage)
    q = mgr.register("run_lc")
    emitter = EventEmitter(run_id="run_lc", manager=mgr, task_id=task["id"])
    lifecycle = TaskLifecycleService(storage, emitter)

    await lifecycle.transition(task["id"], status="running", phase="init")
    await lifecycle.transition(task["id"], status="completed", phase="init")

    events: list = []
    try:
        while True:
            events.append(await asyncio.wait_for(q.get(), timeout=0.1))
    except asyncio.TimeoutError:
        pass

    types = [e.type for e in events]
    assert "task.updated" in types
    assert "task.completed" in types
    # completed arrived after the updated transition.
    assert types.index("task.updated") < types.index("task.completed")

    # Persisted history matches the broadcast order.
    history = mgr.get_history("run_lc")
    htypes = [e.type for e in history]
    assert htypes[-1] == "task.completed"
