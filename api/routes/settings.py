"""Settings API routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from paperforge.config import get_config

router = APIRouter()


class Settings(BaseModel):
    llm_provider: str
    llm_model: str
    max_sandboxes: int


@router.get("", response_model=Settings)
async def get_settings() -> Settings:
    """Get current settings."""
    cfg = get_config()
    return Settings(
        llm_provider=cfg.LLM_PROVIDER,
        llm_model=cfg.LLM_MODEL,
        max_sandboxes=cfg.MAX_SANDBOXES,
    )
