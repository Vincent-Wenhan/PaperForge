from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app


def test_run_state_contains_normalized_recovery_contract(storage):
    storage.create_run("run_state", "State", status="active")
    storage.add_message("run_state", "user", "hello")
    artifact_id = storage.save_artifact(
        "run_state",
        "nextjs_app",
        {"files": [{"path": "app/page.tsx", "content": "export default function Page() {}"}]},
        {"app_path": "server-owned"},
    )
    storage.save_sandbox("sb_old", "run_state", "/old", status="stopped")
    storage.save_sandbox("sb_new", "run_state", "/new", status="running")
    task = storage.create_task("run_state", title="Build", phase="generated")
    approval = storage.create_approval("run_state", "run_in_sandbox", {"artifact_id": artifact_id})
    event = storage.append_run_event(
        run_id="run_state",
        event_id="evt_state",
        event_type="task.phase.changed",
        data={"phase": "generated"},
        task_id=task["id"],
    )

    client = TestClient(create_app())
    response = client.get("/api/runs/run_state/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == "run_state"
    assert payload["messages"][0]["public_id"].startswith("msg_")
    assert payload["artifacts"][0]["id"] == artifact_id
    assert payload["artifacts"][0]["data"]["files"][0]["path"] == "app/page.tsx"
    assert payload["sandbox"]["id"] == "sb_new"
    assert payload["tasks"][0]["id"] == task["id"]
    assert payload["pending_approvals"][0]["approval_id"] == approval["id"]
    assert payload["event_cursor"] == event["seq"]

