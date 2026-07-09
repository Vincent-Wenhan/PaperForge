"""Approval registry for HITL flow.

When the orchestrator encounters a dangerous tool, it creates an approval
record, emits an approval.requested event, and waits for user resolution.
The API endpoint resolves the approval and signals the waiting orchestrator.
"""

from __future__ import annotations

import asyncio


class ApprovalRegistry:
    """Tracks pending approvals and their resolution events."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Event] = {}
        self._results: dict[str, bool] = {}

    def register(self, approval_id: str) -> asyncio.Event:
        """Register a pending approval and return an Event to wait on."""
        ev = asyncio.Event()
        self._pending[approval_id] = ev
        return ev

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """Resolve a pending approval. Returns True if the approval existed."""
        if approval_id not in self._pending:
            return False
        self._results[approval_id] = approved
        self._pending[approval_id].set()
        return True

    def get_result(self, approval_id: str) -> bool | None:
        return self._results.get(approval_id)

    def cleanup(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)
        self._results.pop(approval_id, None)


_registry: ApprovalRegistry | None = None


def get_approval_registry() -> ApprovalRegistry:
    global _registry
    if _registry is None:
        _registry = ApprovalRegistry()
    return _registry
