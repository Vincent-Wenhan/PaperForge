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
    orchestrator_model: str
    parser_model: str
    composer_model: str
    planner_model: str
    generator_model: str
    verifier_model: str
    max_sandboxes: int
    docker_available: bool
    sandbox_image: str
    sandbox_mem_limit: str
    sandbox_cpu_quota: int
    max_iterations: int
    llm_max_retries: int


@router.get("", response_model=Settings)
async def get_settings() -> Settings:
    """Get current settings."""
    cfg = get_config()
    return Settings(
        llm_provider=cfg.LLM_PROVIDER,
        llm_model=cfg.LLM_MODEL,
        orchestrator_model=cfg.ORCHESTRATOR_MODEL,
        parser_model=cfg.PARSER_MODEL,
        composer_model=cfg.COMPOSER_MODEL,
        planner_model=cfg.PLANNER_MODEL,
        generator_model=cfg.GENERATOR_MODEL,
        verifier_model=cfg.VERIFIER_MODEL,
        max_sandboxes=cfg.MAX_SANDBOXES,
        docker_available=docker_available(),
        sandbox_image=cfg.SANDBOX_IMAGE,
        sandbox_mem_limit=cfg.SANDBOX_MEM_LIMIT,
        sandbox_cpu_quota=cfg.SANDBOX_CPU_QUOTA,
        max_iterations=20,
        llm_max_retries=3,
    )
