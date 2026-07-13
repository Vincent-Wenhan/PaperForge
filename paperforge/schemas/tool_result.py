"""Unified tool result schema."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class ToolStatus(str, Enum):
    """Outcome of a tool execution."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ToolResult(BaseModel):
    """Standard result envelope for orchestrator tools.

    `status` is the source of truth. The `ok` property is kept for
    backwards compatibility with legacy callers that only checked `ok`.
    """

    tool: str
    status: ToolStatus = ToolStatus.SUCCEEDED
    artifact_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    error: str | None = None
    retryable: bool = False
    next_phase: str | None = None
    stop_loop: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def ok(self) -> bool:
        return self.status == ToolStatus.SUCCEEDED

    # Backwards-compatible constructor: `ToolResult(ok=True, tool=...)`
    # still works. If `ok=True` is passed, status defaults to SUCCEEDED.
    def __init__(self, **data: Any) -> None:
        ok = data.pop("ok", None)
        if "status" not in data and ok is not None:
            data["status"] = (
                ToolStatus.SUCCEEDED if ok else ToolStatus.FAILED
            )
        super().__init__(**data)
