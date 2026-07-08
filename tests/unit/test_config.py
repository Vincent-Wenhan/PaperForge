"""Tests for the config module."""

from __future__ import annotations

from paperforge.config import get_config, get_settings


def test_default_provider_is_mock():
    cfg = get_config()
    assert cfg.LLM_PROVIDER == "mock"


def test_data_dir_resolved_to_absolute():
    cfg = get_config()
    assert cfg.DATA_DIR.is_absolute()
    assert cfg.DB_PATH.is_absolute()


def test_cors_origins_parsed_as_list():
    cfg = get_config()
    assert isinstance(cfg.CORS_ORIGINS, list)
    assert "http://localhost:3000" in cfg.CORS_ORIGINS


def test_subagent_models_fall_back_to_default():
    cfg = get_config()
    assert cfg.ORCHESTRATOR_MODEL == cfg.LLM_MODEL
    assert cfg.PARSER_MODEL == cfg.LLM_MODEL
