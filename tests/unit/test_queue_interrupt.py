"""Tests for section 15 (Queue / Interrupt / Follow-up) full semantics.

Covers the DB-as-source-of-truth contract: tasks gain priority and
user_message_id, get_next_queued_task drains by priority, and the
RunQueue executor marks queued tasks running/completed so a follow-up
can be queued or interrupt a running task without losing state.
"""

from __future__ import annotations

import asyncio

import pytest

from paperforge.storage.db import Storage


def test_create_task_with_priority_and_user_message_id(storage: Storage):
    run = storage.create_run("run_q1", "Queue", status="active")
    msg = storage.add_message(run_id=run["id"], role="user", content="hello")

    task = storage.create_task(
        run_id=run["id"],
        title="Task",
        goal="hello",
        status="queued",
        phase="init",
        priority=100,
        user_message_id=msg["id"],
    )

    assert task["priority"] == 100
    assert task["user_message_id"] == msg["id"]
    stored = storage.get_task(task["id"])
    assert stored["priority"] == 100
    assert stored["user_message_id"] == msg["id"]


def test_get_next_queued_task_orders_by_priority_then_age(storage: Storage):
    run = storage.create_run("run_q2", "Queue", status="active")
    low = storage.create_task(
        run_id=run["id"], title="low", goal="low",
        status="queued", priority=0,
    )
    high = storage.create_task(
        run_id=run["id"], title="high", goal="high",
        status="queued", priority=100,
    )

    # High-priority (interrupt) is drained first even though it was created last.
    next_task = storage.get_next_queued_task(run["id"])
    assert next_task["id"] == high["id"]

    storage.update_task(task_id=high["id"], status="completed")
    next_task = storage.get_next_queued_task(run["id"])
    assert next_task["id"] == low["id"]

    storage.update_task(task_id=low["id"], status="completed")
    assert storage.get_next_queued_task(run["id"]) is None


def test_get_next_queued_task_skips_non_queued_statuses(storage: Storage):
    run = storage.create_run("run_q3", "Queue", status="active")
    done = storage.create_task(
        run_id=run["id"], title="done", goal="done",
        status="completed", priority=100,
    )
    assert storage.get_next_queued_task(run["id"]) is None
    assert done["status"] == "completed"


@pytest.mark.asyncio
async def test_run_queue_marks_task_running_then_completed(storage: Storage):
    """RunQueue drives task status so the DB is the source of truth."""
    from paperforge.orchestrator.tasks import RunQueue

    run = storage.create_run("run_q4", "Queue", status="active")
    storage.add_message(run_id=run["id"], role="user", content="hello")

    task = storage.create_task(
        run_id=run["id"], title="Task", goal="hello", status="queued",
    )

    # The queue stores only the task id and rebuilds execution from the DB —
    # no coroutine is passed through, so a restart can recover queued work.
    queue = RunQueue(storage=storage)
    await queue.enqueue(run["id"], task["id"])

    # Wait for the worker to drain the single queued task.
    for _ in range(100):
        if not queue.running(run["id"]) and queue._workers.get(run["id"]) is None:
            break
        await asyncio.sleep(0.05)

    await queue.cancel_and_wait(run["id"])
    stored = storage.get_task(task["id"])
    assert stored["status"] == "completed"
