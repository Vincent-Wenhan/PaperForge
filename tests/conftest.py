"""Shared pytest fixtures."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from paperforge.config import reset_config, reset_settings
from paperforge.storage.db import reset_storage
from paperforge.orchestrator.approvals import reset_approval_registry
from paperforge.orchestrator.events import reset_event_manager


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets a fresh data dir and database."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "test.db"

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    reset_settings()
    reset_config()
    reset_storage()
    reset_event_manager()
    reset_approval_registry()
    yield
    reset_settings()
    reset_config()
    reset_storage()
    reset_event_manager()
    reset_approval_registry()


@pytest.fixture
def storage(isolated_env):
    from paperforge.storage.db import get_storage
    return get_storage()


@pytest.fixture
def workspace_artifact(storage, tmp_path):
    """A run with a generated nextjs_app artifact (workspace resource)."""
    run = storage.create_run(f"run_{uuid.uuid4().hex[:8]}", title="Workspace run")
    app_path = tmp_path / "apps" / "app_1"
    app_path.mkdir(parents=True)
    artifact_id = storage.save_artifact(
        run_id=run["id"],
        artifact_type="nextjs_app",
        data={"app_id": "app_1"},
        metadata={"app_path": str(app_path)},
    )
    storage.create_workspace_revision(
        run_id=run["id"],
        app_id=artifact_id,
        source="generator",
        app_path=str(app_path),
    )
    return type("WorkspaceArtifact", (), {"run_id": run["id"], "app_path": app_path, "artifact_id": artifact_id})()


@pytest.fixture
def mock_llm():
    from paperforge.llm.mock_provider import MockLLMClient
    return MockLLMClient()
