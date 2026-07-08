"""Configuration loader. Reads from environment / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Sub-agent models (empty → falls back to LLM_MODEL)
    ORCHESTRATOR_MODEL: str = ""
    PARSER_MODEL: str = ""
    COMPOSER_MODEL: str = ""
    PLANNER_MODEL: str = ""
    GENERATOR_MODEL: str = ""
    VERIFIER_MODEL: str = ""

    # Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000"

    # Sandbox
    MAX_SANDBOXES: int = 3
    SANDBOX_IMAGE: str = "node:20-alpine"
    SANDBOX_MEM_LIMIT: str = "1g"
    SANDBOX_CPU_QUOTA: int = 50000

    # Storage
    DATA_DIR: str = "./data"
    DB_PATH: str = "./data/paperforge.db"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None


class Config(BaseModel):
    """Resolved configuration used inside paperforge modules."""

    LLM_PROVIDER: str
    LLM_API_KEY: str
    LLM_BASE_URL: str
    LLM_MODEL: str
    ORCHESTRATOR_MODEL: str
    PARSER_MODEL: str
    COMPOSER_MODEL: str
    PLANNER_MODEL: str
    GENERATOR_MODEL: str
    VERIFIER_MODEL: str
    MAX_SANDBOXES: int
    SANDBOX_IMAGE: str
    SANDBOX_MEM_LIMIT: str
    SANDBOX_CPU_QUOTA: int
    DATA_DIR: Path
    DB_PATH: Path
    CORS_ORIGINS: list[str]


def load_config() -> Config:
    s = get_settings()

    def model_or_default(v: str) -> str:
        return v or s.LLM_MODEL

    data_dir = Path(s.DATA_DIR).resolve()
    db_path = Path(s.DB_PATH).resolve()
    return Config(
        LLM_PROVIDER=s.LLM_PROVIDER,
        LLM_API_KEY=s.LLM_API_KEY,
        LLM_BASE_URL=s.LLM_BASE_URL,
        LLM_MODEL=s.LLM_MODEL,
        ORCHESTRATOR_MODEL=model_or_default(s.ORCHESTRATOR_MODEL),
        PARSER_MODEL=model_or_default(s.PARSER_MODEL),
        COMPOSER_MODEL=model_or_default(s.COMPOSER_MODEL),
        PLANNER_MODEL=model_or_default(s.PLANNER_MODEL),
        GENERATOR_MODEL=model_or_default(s.GENERATOR_MODEL),
        VERIFIER_MODEL=model_or_default(s.VERIFIER_MODEL),
        MAX_SANDBOXES=s.MAX_SANDBOXES,
        SANDBOX_IMAGE=s.SANDBOX_IMAGE,
        SANDBOX_MEM_LIMIT=s.SANDBOX_MEM_LIMIT,
        SANDBOX_CPU_QUOTA=s.SANDBOX_CPU_QUOTA,
        DATA_DIR=data_dir,
        DB_PATH=db_path,
        CORS_ORIGINS=[o.strip() for o in s.CORS_ORIGINS.split(",") if o.strip()],
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    global _config
    _config = None
