"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from paperforge.config import reset_config, reset_settings
from paperforge.storage.db import reset_storage
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
    yield
    reset_settings()
    reset_config()
    reset_storage()
    reset_event_manager()


@pytest.fixture
def storage(isolated_env):
    from paperforge.storage.db import get_storage
    return get_storage()


@pytest.fixture
def mock_llm():
    from paperforge.llm.mock_provider import MockLLMClient
    return MockLLMClient()
