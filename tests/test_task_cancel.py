from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from paperforge.orchestrator.loop import Orchestrator
from paperforge.orchestrator.tasks import RunTaskManager


@pytest.mark.asyncio
async def test_cancel_and_wait_drains_task():
    manager = RunTaskManager()
    finished = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(10)
        finally:
            finished.set()

    manager.start("run_cancel", work())
    await asyncio.sleep(0)
    assert await manager.cancel_and_wait("run_cancel", timeout=1)
    assert finished.is_set()
    assert not manager.is_running("run_cancel")


def test_cancel_endpoint_stops_active_task_but_run_stays_active(storage):
    storage.create_run("run_cancel_api", "Cancel", status="running")

    response = TestClient(create_app()).post("/api/runs/run_cancel_api/cancel")

    assert response.status_code == 200
    # Task-level stop: the run stays an active persistent thread.
    assert storage.get_run_status("run_cancel_api") == "active"


@pytest.mark.asyncio
async def test_archived_run_does_not_resume_work(storage):
    storage.create_run("run_archived", "Archived", status="active")
    storage.archive_run("run_archived")

    class FailingLLM:
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("archived run must not call the LLM")

    llm = FailingLLM()
    await Orchestrator(llm=llm, storage=storage).run(
        "run_archived",
        "resume",
    )

    assert llm.calls == 0


@pytest.mark.asyncio
async def test_cancelled_run_can_still_resume_work(storage):
    """A 'cancelled' run status is not terminal — the persistent thread can
    resume. Only archive blocks a new task."""
    storage.create_run("run_cancelled_but_active", "Cancelled", status="cancelled")

    from paperforge.llm.base import ChatResponse

    class ReraisingLLM:
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            # Emulate a hard provider error so the orchestrator bails through
            # its retry path. The point is that it *entered* the LLM call
            # rather than short-circuiting on a cancelled status.
            raise RuntimeError("provider down")

    llm = ReraisingLLM()
    orchestrator = Orchestrator(llm=llm, storage=storage)
    orchestrator.llm = llm
    await orchestrator.run("run_cancelled_but_active", "resume")

    # The run was not blocked at the status gate; it attempted real work.
    assert llm.calls > 0
    assert storage.get_run_status("run_cancelled_but_active") == "error"
