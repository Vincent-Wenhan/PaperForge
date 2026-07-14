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


def test_cancel_endpoint_persists_terminal_status_and_event(storage):
    storage.create_run("run_cancel_api", "Cancel", status="running")

    response = TestClient(create_app()).post("/api/runs/run_cancel_api/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert storage.get_run_status("run_cancel_api") == "cancelled"
    assert storage.get_max_event_seq("run_cancel_api") >= 1


@pytest.mark.asyncio
async def test_cancelled_run_does_not_resume_work(storage):
    storage.create_run("run_cancelled", "Cancelled", status="cancelled")

    class FailingLLM:
        calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("cancelled run must not call the LLM")

    llm = FailingLLM()
    await Orchestrator(llm=llm, storage=storage).run(
        "run_cancelled",
        "resume",
    )

    assert llm.calls == 0
    assert storage.get_run_status("run_cancelled") == "cancelled"
