"""Tests for section 16 (Task/Step observable execution model).

Verifies per-task steps are queryable independently and survive a reload,
and that messages carry task_id so the frontend can project turns.
"""

from __future__ import annotations

from paperforge.storage.db import Storage


def test_steps_are_queryable_per_task(storage: Storage):
    run = storage.create_run("run_s1", "Steps", status="active")
    task_a = storage.create_task(run_id=run["id"], title="A", status="queued")
    task_b = storage.create_task(run_id=run["id"], title="B", status="queued")

    step_a = storage.create_step(
        task_id=task_a["id"], run_id=run["id"], kind="tool", title="Read file",
    )
    step_b = storage.create_step(
        task_id=task_b["id"], run_id=run["id"], kind="tool", title="Plan",
    )

    steps_a = storage.list_steps_by_task(task_a["id"])
    steps_b = storage.list_steps_by_task(task_b["id"])

    assert [s["id"] for s in steps_a] == [step_a["id"]]
    assert [s["id"] for s in steps_b] == [step_b["id"]]

    storage.complete_step(step_a["id"], summary="done")
    assert storage.list_steps_by_task(task_a["id"])[0]["status"] == "completed"


def test_steps_survive_reload_from_db(storage: Storage):
    run = storage.create_run("run_s2", "Steps", status="active")
    task = storage.create_task(run_id=run["id"], title="A", status="queued")
    step = storage.create_step(
        task_id=task["id"], run_id=run["id"], kind="tool", title="Build",
    )
    storage.complete_step(step["id"], summary="built")

    # Re-open the storage layer as if from a fresh request; steps persist.
    from paperforge.storage.db import get_storage

    fresh = get_storage()
    rows = fresh.list_steps_by_task(task["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["summary"] == "built"


def test_messages_carry_task_id(storage: Storage):
    run = storage.create_run("run_s3", "Messages", status="active")
    task = storage.create_task(run_id=run["id"], title="A", status="queued")

    storage.add_message(
        run_id=run["id"], role="assistant", content="hello", task_id=task["id"],
    )
    msg = storage.list_messages(run["id"])[0]
    assert msg["task_id"] == task["id"]
