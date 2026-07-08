"""Tests for the FastAPI backend."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_list_runs():
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/runs", json={"title": "Test Run"})
    assert r.status_code == 200
    run_id = r.json()["id"]
    assert run_id.startswith("run_")

    r = client.get("/api/runs")
    assert r.status_code == 200
    assert any(r["id"] == run_id for r in r.json())


def test_get_run_by_id():
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/runs", json={"title": "Get Run"})
    run_id = r.json()["id"]

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Get Run"


def test_delete_run():
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/runs", json={"title": "Delete Run"})
    run_id = r.json()["id"]

    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 200

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 404


def test_list_messages_empty():
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/runs", json={"title": "Msg Run"})
    run_id = r.json()["id"]

    r = client.get(f"/api/runs/{run_id}/messages")
    assert r.status_code == 200
    assert r.json() == []


def test_list_papers():
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/library")
    assert r.status_code == 200
    assert "papers" in r.json()
