"""Queue concurrency hardening tests (2026-08-13 doc, §14–15, §54.4)."""

from __future__ import annotations

import asyncio

import pytest

from paperforge.orchestrator.tasks import RunTaskManager


@pytest.mark.asyncio
async def test_old_task_done_callback_cannot_evict_replacement():
    manager = RunTaskManager()

    old_started = asyncio.Event()
    old_finished = asyncio.Event()

    async def old():
        try:
            await asyncio.sleep(100)
        finally:
            old_finished.set()

    async def new():
        # Keeps running after the old task's callback fires.
        await asyncio.Event().wait()

    manager.start("run_1", old())
    replacement = manager.start("run_1", new())

    # Give the event loop a chance to deliver the cancellation to `old`,
    # running its finally and its done callback.
    for _ in range(10):
        await asyncio.sleep(0)
        if old_finished.is_set():
            break

    # The old task's done callback must not have evicted the replacement.
    assert manager.tasks.get("run_1") is replacement

    replacement.cancel()
    with pytest.raises(asyncio.CancelledError):
        await replacement


@pytest.mark.asyncio
async def test_normal_completion_still_cleans_up_manager():
    manager = RunTaskManager()

    async def work():
        await asyncio.sleep(0.05)

    task = manager.start("run_2", work())
    await asyncio.sleep(0.2)

    assert task.done()
    assert manager.tasks.get("run_2") is None
