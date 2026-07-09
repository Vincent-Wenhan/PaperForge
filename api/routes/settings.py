"""Settings API routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from paperforge.config import get_config
from paperforge.sandbox.docker_runner import docker_available

router = APIRouter()


class Settings(BaseModel):
    llm_provider: str
    llm_model: str
    max_sandboxes: int
    docker_available: bool


@router.get("", response_model=Settings)
async def get_settings() -> Settings:
    """Get current settings."""
    cfg = get_config()
    return Settings(
        llm_provider=cfg.LLM_PROVIDER,
        llm_model=cfg.LLM_MODEL,
        max_sandboxes=cfg.MAX_SANDBOXES,
        docker_available=docker_available(),
    )
