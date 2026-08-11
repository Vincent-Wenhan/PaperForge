"""Tests for PR-D: Generation V3 is wired into handle_generate.

The handler must route through generation_v3.generate_nextjs_app_v3 (plan
then bounded batches) instead of the old single-call V2 giant-JSON path.
"""

from __future__ import annotations

import asyncio
import unittest.mock as mock

import pytest

from paperforge.orchestrator.tools import ToolContext, handle_generate


@pytest.mark.asyncio
async def test_generate_routes_through_v3(monkeypatch):
    """handle_generate calls generate_nextjs_app_v3, not the V2 generator."""
    called = {"v2": False, "v3": False}

    import paperforge.agents.generation_v3 as generation_v3

    async def fake_v3(*, prd_id, output_dir, llm, storage, progress):
        called["v3"] = True
        return {
            "app_id": "app_1",
            "plan": {},
            "files": [],
            "dependencies": {},
            "output_dir": str(output_dir),
        }

    monkeypatch.setattr(
        generation_v3, "generate_nextjs_app_v3", fake_v3
    )

    # Fail loudly if handle_generate imports the V2 generator.
    import paperforge.agents.nextjs_generator as nextjs_gen

    def _bad_v2(*a, **k):
        called["v2"] = True
        raise AssertionError("Generation V2 main path must not be used")

    monkeypatch.setattr(nextjs_gen, "generate_nextjs_app", _bad_v2)

    progress = mock.MagicMock()
    progress.start = mock.AsyncMock(return_value="step1")
    progress.complete = mock.AsyncMock()
    progress.fail = mock.AsyncMock()

    storage = mock.MagicMock()
    storage.apps_dir  # Path attribute used for output_dir
    storage.apps_dir.__truediv__.return_value = "app_out"
    import pathlib
    storage.apps_dir = pathlib.Path("apps_root")

    llm = mock.MagicMock()
    emit = mock.MagicMock()
    emit.artifact_created = mock.AsyncMock()
    # handle_generate saves the app artifact; return a real id.
    storage.save_artifact = mock.MagicMock(return_value="nextjs_app_abc")
    ctx = ToolContext(
        run_id="run_g",
        storage=storage,
        llm=llm,
        emit=emit,
        task_id="task_g",
    )
    ctx.progress = lambda task_id=None: progress

    result = await handle_generate({"prd_id": "prd_1"}, ctx)

    assert called["v3"] is True
    assert called["v2"] is False
    assert result.status.value == "succeeded"
