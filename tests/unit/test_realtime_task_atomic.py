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


@pytest.mark.asyncio
async def test_terminal_events_are_distinct(storage):
    """failed and cancelled must broadcast distinct events, not task.completed."""
    run = storage.create_run("run_term", "Terminal", status="active")

    def collect():
        mgr = EventManager(storage=storage)
        q = mgr.register(run["id"])
        emitter = EventEmitter(run_id=run["id"], manager=mgr, task_id=None)
        return mgr, q, emitter

    # failed
    t_fail = storage.create_task(run_id=run["id"], title="f", goal="g",
                                 status="running", phase="init")
    mgr, q, emitter = collect()
    lifecycle = TaskLifecycleService(storage, emitter)
    await lifecycle.transition(t_fail["id"], status="failed", phase="init")
    types_fail = [(await q.get()).type]
    assert types_fail == ["task.failed"]
    assert mgr.get_history(run["id"])[-1].type == "task.failed"

    # cancelled
    t_cancel = storage.create_task(run_id=run["id"], title="c", goal="g",
                                   status="running", phase="init")
    mgr, q, emitter = collect()
    lifecycle = TaskLifecycleService(storage, emitter)
    await lifecycle.transition(t_cancel["id"], status="cancelled", phase="init")
    types_cancel = [(await q.get()).type]
    assert types_cancel == ["task.cancelled"]
    assert mgr.get_history(run["id"])[-1].type == "task.cancelled"

    # Non-terminal stays task.updated.
    t_prog = storage.create_task(run_id=run["id"], title="p", goal="g",
                                 status="queued", phase="init")
    mgr, q, emitter = collect()
    lifecycle = TaskLifecycleService(storage, emitter)
    await lifecycle.transition(t_prog["id"], status="running", phase="init")
    types_prog = [(await q.get()).type]
    assert types_prog == ["task.updated"]

    # DB final states are persisted and distinct.
    assert storage.get_task(t_fail["id"])["status"] == "failed"
    assert storage.get_task(t_cancel["id"])["status"] == "cancelled"
    assert storage.get_task(t_prog["id"])["status"] == "running"


@pytest.mark.asyncio
async def test_lifecycle_requeue_and_anomaly_fail_route_through_service(storage):
    """Queue requeue (lost lease) and anomaly fail go through lifecycle so
    the event contract (task.updated on requeue, task.failed on anomaly)
    and DB state stay consistent."""
    from paperforge.orchestrator.tasks import RunQueue

    run = storage.create_run("run_rr", "Recover", status="active")
    q_task = storage.create_task(run_id=run["id"], title="q", goal="g",
                                 status="running", phase="init")

    # requeue path (lost lease): running -> queued, emits task.updated.
    queue = RunQueue(storage=storage)
    await queue._requeue(run["id"], q_task["id"], storage)
    assert storage.get_task(q_task["id"])["status"] == "queued"

    # anomaly path (exited while running): running -> failed, emits task.failed.
    f_task = storage.create_task(run_id=run["id"], title="f", goal="g",
                                 status="running", phase="init")
    await queue._fail_anomaly(run["id"], f_task["id"], storage)
    assert storage.get_task(f_task["id"])["status"] == "failed"

    # persisted event seq covers both.
    from paperforge.orchestrator.events import get_event_manager
    history = get_event_manager().get_history(run["id"])
    types = {e.type for e in history}
    assert "task.failed" in types
