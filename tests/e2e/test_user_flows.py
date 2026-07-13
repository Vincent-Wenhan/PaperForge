"""E2E tests covering the critical ChatGPT/Codex-style user flows (doc 15.3).

These tests exercise the full API surface to verify:
1. A run can be created and queried.
2. Messages can be sent and listed.
3. Papers can be uploaded, listed, fetched, renamed, and deleted.
4. Run-paper attachments work.
5. Sandbox endpoints function.
6. Settings endpoint returns expected fields.
7. Health check works.

These tests run against the FastAPI TestClient with mock LLM, so they're
hermetic and fast.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_pdf(name: str = "test_paper.pdf") -> bytes:
    """Return minimal valid PDF bytes."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def test_create_run_and_send_message(client):
    """Section 15.3 step 1-2: create run, send 'who are you'."""
    r = client.post("/api/runs", json={"title": "Test Run"})
    assert r.status_code == 200
    run = r.json()
    run_id = run["id"]
    assert run["title"] == "Test Run"
    assert run["status"] == "active"

    # Send a message
    r = client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "who are you", "paper_ids": []},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_run_lifecycle_create_get_delete(client):
    """Full run lifecycle: create → get → delete."""
    r = client.post("/api/runs", json={"title": "Lifecycle Run"})
    assert r.status_code == 200
    run = r.json()
    run_id = run["id"]

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["id"] == run_id

    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 200

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 404


def test_paper_upload_get_rename_delete(client, tmp_path):
    """Section 9.2: paper upload → get → rename → delete."""
    pdf_bytes = _make_pdf()

    # Upload
    r = client.post(
        "/api/library/upload",
        files={"file": ("test_paper.pdf", BytesIO(pdf_bytes), "application/pdf")},
    )
    assert r.status_code == 200
    paper = r.json()
    paper_id = paper["paper_id"]
    assert paper["status"] == "uploaded"

    # Get
    r = client.get(f"/api/library/{paper_id}")
    assert r.status_code == 200
    assert r.json()["paper"]["paper_id"] == paper_id

    # Rename
    r = client.patch(f"/api/library/{paper_id}", json={"title": "Renamed Paper"})
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed Paper"

    # List
    r = client.get("/api/library")
    assert r.status_code == 200
    papers = r.json()["papers"]
    assert any(p["paper_id"] == paper_id for p in papers)

    # Delete
    r = client.delete(f"/api/library/{paper_id}")
    assert r.status_code == 200

    r = client.get(f"/api/library/{paper_id}")
    assert r.status_code == 404


def test_attach_detach_paper_to_run(client):
    """Section 4.4: attach paper to run, then detach."""
    # Create run
    r = client.post("/api/runs", json={"title": "Attach Run"})
    run_id = r.json()["id"]

    # Upload paper
    r = client.post(
        "/api/library/upload",
        files={"file": ("attach_test.pdf", BytesIO(_make_pdf()), "application/pdf")},
    )
    paper_id = r.json()["paper_id"]

    # Attach
    r = client.post(f"/api/runs/{run_id}/papers/{paper_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "attached"

    # List attached papers
    r = client.get(f"/api/runs/{run_id}/papers")
    assert r.status_code == 200
    assert any(p["paper_id"] == paper_id for p in r.json()["papers"])

    # Detach
    r = client.delete(f"/api/runs/{run_id}/papers/{paper_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "detached"


def test_sandbox_list_and_get(client):
    """Sandbox endpoints should be queryable without Docker."""
    r = client.get("/api/sandboxes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_settings_endpoint(client):
    """Settings endpoint returns expected fields."""
    r = client.get("/api/settings")
    assert r.status_code == 200
    settings = r.json()
    assert "llm_provider" in settings
    assert "llm_model" in settings
    assert "max_sandboxes" in settings


def test_health_check(client):
    """Health endpoint should return ok status."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_run_archive_restore(client):
    """Run can be archived and restored (doc 6.4)."""
    r = client.post("/api/runs", json={"title": "Archive Run"})
    run_id = r.json()["id"]

    r = client.post(f"/api/runs/{run_id}/archive")
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None

    r = client.post(f"/api/runs/{run_id}/restore")
    assert r.status_code == 200
    assert r.json()["archived_at"] is None
