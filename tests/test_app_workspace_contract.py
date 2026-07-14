from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app
from api.routes.apps import MAX_FILE_SIZE


def test_app_workspace_checks_run_ownership_and_input_size(storage):
    storage.create_run("run_app_a", "App A", status="active")
    storage.create_run("run_app_b", "App B", status="active")
    app_path = storage.apps_dir / "generated"
    app_path.mkdir()
    artifact_id = storage.save_artifact(
        "run_app_a",
        "nextjs_app",
        {"app_path": str(app_path)},
        {"app_path": str(app_path)},
    )
    client = TestClient(create_app())

    forbidden = client.get(
        f"/api/apps/{artifact_id}/tree",
        params={"run_id": "run_app_b"},
    )
    assert forbidden.status_code == 403

    oversized = client.put(
        f"/api/apps/{artifact_id}/files/app/page.tsx",
        json={"content": "x" * (MAX_FILE_SIZE + 1)},
        params={"run_id": "run_app_a"},
    )
    assert oversized.status_code == 413

    invalid = client.post(
        f"/api/apps/{artifact_id}/entries",
        json={"type": "symlink", "path": "app/link.ts"},
        params={"run_id": "run_app_a"},
    )
    assert invalid.status_code == 400
