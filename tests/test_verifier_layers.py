from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from paperforge.agents.verifier import verify_app


def test_preview_status_exposes_degraded_and_running_states(storage, tmp_path):
    storage.create_run("run_preview", "Preview", status="active")
    client = TestClient(create_app())

    idle = client.get("/api/preview/status/run_preview")
    assert idle.status_code == 200
    assert idle.json()["status"] == "idle"

    root = tmp_path / "app"
    root.mkdir()
    storage.save_sandbox("sb_error", "run_preview", str(root), status="error")
    degraded = client.get("/api/preview/status/run_preview")
    assert degraded.status_code == 200
    assert degraded.json()["status"] == "degraded"

    storage.save_sandbox("sb_running", "run_preview", str(root), status="running")
    running = client.get("/api/preview/status/run_preview")
    assert running.status_code == 200
    assert running.json()["status"] == "running"
    assert running.json()["sandbox_id"] == "sb_running"


async def _empty_verification(storage, tmp_path):
    app_path = tmp_path / "empty"
    app_path.mkdir()
    return await verify_app(
        app_path=app_path,
        prd_id=None,
        llm=None,  # type: ignore[arg-type]
        storage=storage,
    )


@pytest.mark.asyncio
async def test_verifier_returns_structured_layer_results(storage, tmp_path):
    report = await _empty_verification(storage, tmp_path)

    layers = {layer["id"]: layer for layer in report["layers"]}
    assert {"workspace", "static", "build", "runtime", "acceptance"} <= set(layers)
    assert layers["workspace"]["status"] == "failed"
    assert layers["runtime"]["status"] == "pending"
