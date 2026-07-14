from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app


def test_workspace_revision_diff_and_restore(storage):
    storage.create_run("run_revision", "Revision", status="active")
    app_path = storage.apps_dir / "app_revision"
    app_path.mkdir()
    (app_path / "app").mkdir()
    (app_path / "app" / "page.tsx").write_text("export default function Page() { return 'one'; }", encoding="utf-8")
    (app_path / "README.md").write_text("first", encoding="utf-8")
    app_id = storage.save_artifact(
        "run_revision",
        "nextjs_app",
        {"app_path": str(app_path)},
        {"app_path": str(app_path)},
    )
    first = storage.create_workspace_revision(
        "run_revision",
        app_id,
        "generator",
        app_path,
    )

    (app_path / "app" / "page.tsx").write_text("export default function Page() { return 'two'; }", encoding="utf-8")
    (app_path / "new.ts").write_text("export const added = true;", encoding="utf-8")
    second = storage.create_workspace_revision(
        "run_revision",
        app_id,
        "user_edit",
        app_path,
    )

    client = TestClient(create_app())
    detail = client.get(
        f"/api/apps/{app_id}/revisions/{second['id']}",
        params={"run_id": "run_revision"},
    )
    assert detail.status_code == 200
    changed = {item["path"]: item for item in detail.json()["files"]}
    assert changed["app/page.tsx"]["before"].endswith("'one'; }")
    assert changed["new.ts"]["before"] is None

    restored = client.post(
        f"/api/apps/{app_id}/revisions/{first['id']}/restore",
        params={"run_id": "run_revision"},
    )
    assert restored.status_code == 200
    assert (app_path / "app" / "page.tsx").read_text(encoding="utf-8").endswith("'one'; }")
    assert not (app_path / "new.ts").exists()


def test_preview_ready_is_separate_from_container_running(storage):
    storage.create_run("run_preview_state", "Preview", status="active")
    storage.save_sandbox(
        "sb_preview_state",
        "run_preview_state",
        str(storage.apps_dir / "app_preview"),
        status="running",
        preview_status="starting",
    )
    client = TestClient(create_app())

    starting = client.get("/api/runs/run_preview_state/state")
    assert starting.status_code == 200
    assert starting.json()["preview"]["status"] == "starting"

    storage.update_sandbox(
        "sb_preview_state",
        preview_status="running",
        preview_url="/api/preview/sb_preview_state/",
    )
    ready = client.get("/api/preview/status/run_preview_state")
    assert ready.status_code == 200
    assert ready.json()["status"] == "running"
    assert ready.json()["preview_url"].endswith("/")


def test_artifact_payload_updates_in_place(storage):
    storage.create_run("run_artifact_update", "Artifacts", status="active")
    artifact_id = storage.save_artifact(
        "run_artifact_update",
        "verification_report",
        {"runtime_status": "pending"},
    )

    updated = storage.update_artifact(
        artifact_id,
        data={"runtime_status": "passed"},
        metadata={"source": "sandbox"},
    )

    assert updated is not None
    assert updated["data"]["runtime_status"] == "passed"
    assert updated["metadata"]["source"] == "sandbox"
    assert updated["version"] == 2
