"""Shared FastAPI dependencies.

Provides singletons (storage, event_manager, llm_client, sandbox_manager)
to route handlers via Depends(). Keeps routes thin and testable.
"""

from __future__ import annotations

from fastapi import Request

from paperforge.llm.base import LLMClient
from paperforge.llm.factory import get_llm_client
from paperforge.orchestrator.events import EventManager, get_event_manager
from paperforge.sandbox.docker_runner import DockerSandboxManager
from paperforge.storage.db import Storage, get_storage


def get_storage_dep(request: Request) -> Storage:
    """Return the storage singleton."""
    return get_storage()


def get_event_manager_dep(request: Request) -> EventManager:
    """Return the event manager singleton."""
    return get_event_manager()


def get_llm_client_dep(request: Request) -> LLMClient:
    """Return the LLM client singleton."""
    return get_llm_client()


def get_sandbox_manager_dep(request: Request) -> DockerSandboxManager | None:
    """Return the sandbox manager if Docker is available, else None."""
    return getattr(request.app.state, "sandbox_manager", None)
