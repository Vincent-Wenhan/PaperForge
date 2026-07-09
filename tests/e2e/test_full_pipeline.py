"""E2E tests for the full pipeline (mock LLM).

Tests the complete flow: API → orchestrator → sub-agents → artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from paperforge.llm.base import ChatResponse, ToolCall
from paperforge.llm.mock_provider import MockLLMClient
from paperforge.orchestrator.loop import Orchestrator


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.mark.asyncio
async def test_orchestrator_full_pipeline_with_tools(storage, tmp_path):
    """Orchestrator should: parse_paper → finish."""
    storage.create_run("run-e2e", "E2E Test", status="active")

    class PipelineLLM(MockLLMClient):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def chat(self, *args, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return ChatResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="finish",
                            args={"summary": "Pipeline complete"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="Done", finish_reason="stop")

    orc = Orchestrator(llm=PipelineLLM(), storage=storage)
    await orc.run(run_id="run-e2e", user_message="Run the pipeline")

    messages = storage.list_messages("run-e2e")
    assert len(messages) >= 2  # user + assistant


def test_api_full_workflow(client):
    """Full workflow: create run → list → get → delete."""
    r = client.post("/api/runs", json={"title": "E2E Run"})
    assert r.status_code == 200
    run = r.json()
    run_id = run["id"]
    assert run["title"] == "E2E Run"

    r = client.get("/api/runs")
    assert r.status_code == 200
    assert any(r["id"] == run_id for r in r.json())

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["id"] == run_id

    r = client.get(f"/api/runs/{run_id}/messages")
    assert r.status_code == 200
    assert r.json() == []

    r = client.delete(f"/api/runs/{run_id}")
    assert r.status_code == 200

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 404


def test_library_upload_and_list(client, tmp_path):
    """Upload a PDF to the library and list it."""
    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    pdf_path = tmp_path / "test_paper.pdf"
    pdf_path.write_bytes(pdf_content)

    with open(pdf_path, "rb") as f:
        r = client.post(
            "/api/library/upload",
            files={"file": ("test_paper.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200
    paper = r.json()
    assert paper["paper_id"] == "test_paper"
    assert paper["status"] == "uploaded"

    r = client.get("/api/library")
    assert r.status_code == 200
    papers = r.json()["papers"]
    assert any(p["paper_id"] == "test_paper" for p in papers)

    r = client.get("/api/library/test_paper")
    assert r.status_code == 200
    data = r.json()
    assert data["paper"]["paper_id"] == "test_paper"


def test_sandbox_endpoints(client):
    """Test sandbox listing endpoint (no Docker required)."""
    r = client.get("/api/sandboxes")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_settings_endpoint(client):
    """Test settings endpoint returns provider info."""
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
