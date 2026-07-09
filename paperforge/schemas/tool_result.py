"""Unified tool result schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard result envelope for orchestrator tools."""

    ok: bool
    tool: str
    artifact_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    error: str | None = None
