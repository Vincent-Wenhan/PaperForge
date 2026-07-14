from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app


def test_approval_list_and_resolution_are_durable(storage):
    storage.create_run("run_approval", "Approval", status="active")
    approval = storage.create_approval(
        "run_approval",
        "generate_nextjs_app",
        {"artifact_id": "app_123"},
    )

    client = TestClient(create_app())
    listed = client.get("/api/approvals", params={"run_id": "run_approval"})
    assert listed.status_code == 200
    assert listed.json()[0]["approval_id"] == approval["id"]
    assert listed.json()[0]["status"] == "pending"
    assert listed.json()[0]["run_id"] == "run_approval"

    resolved = client.post(
        f"/api/approvals/{approval['id']}/resolve",
        json={"approved": True},
    )
    assert resolved.status_code == 200
    assert resolved.json()["approval_id"] == approval["id"]
    assert resolved.json()["status"] == "approved"

    repeated = client.post(
        f"/api/approvals/{approval['id']}/resolve",
        json={"approved": False},
    )
    assert repeated.status_code == 409

