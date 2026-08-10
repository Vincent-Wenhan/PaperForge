"""Approval registry + risk-based approval policy for HITL flow.

The registry just tracks pending approvals and their resolution events.
The policy decides whether a tool needs approval at all — using a
risk-based model (doc 17) instead of a flat dangerous-tool set, so a
workspace write inside an isolated local sandbox does not prompt on every
edit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

ToolRisk = Literal[
    "read", "workspace_write", "sandbox_exec", "network", "destructive"
]


class ApprovalMode(str, Enum):
    ALWAYS = "always"
    TRUST_WORKSPACE = "trust_workspace"
    MANUAL = "manual"


@dataclass(frozen=True)
class ToolSpec:
    """Minimal risk descriptor used by the approval policy."""

    name: str
    risk: ToolRisk = "read"


@dataclass(frozen=True)
class ApprovalPolicy:
    """Risk-based gating for whether a tool requires HITL approval (doc 17).

    - ``ALWAYS``: every non-read tool prompts.
    - ``MANUAL``: nothing prompts; the user resolves everything by hand.
    - ``TRUST_WORKSPACE`` (default): reads and workspace writes are trusted,
      sandbox exec is trusted when the workspace is isolated, and only
      network/destructive operations prompt. This lets a continuous agent
      patch its own workspace without a modal every turn.
    """

    mode: ApprovalMode = ApprovalMode.TRUST_WORKSPACE
    workspace_isolated: bool = True
    network_enabled: bool = False

    def requires(self, spec: ToolSpec) -> bool:
        if self.mode == ApprovalMode.ALWAYS:
            return spec.risk != "read"
        if self.mode == ApprovalMode.MANUAL:
            return False
        if spec.risk in {"read", "workspace_write"}:
            return False
        if spec.risk == "sandbox_exec":
            return not self.workspace_isolated
        return spec.risk in {"network", "destructive"}


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

    async def wait_for_resolution(
        self,
        approval_id: str,
        storage: Any,
        timeout: float,
        poll_interval: float = 0.25,
    ) -> bool | None:
        """Wait on fast in-memory signals while treating SQLite as truth.

        The database check makes approval waits recoverable when the API
        resolves an approval after a worker restart or before the registry
        has finished registering its in-memory event.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        event = self._pending.get(approval_id)

        while True:
            row = storage.get_approval(approval_id)
            if row is None:
                return False
            if row["status"] != "pending":
                return row["status"] == "approved"

            remaining = deadline - loop.time()
            if remaining <= 0:
                return None

            wait_for = min(poll_interval, remaining)
            if event is None:
                await asyncio.sleep(wait_for)
                continue
            try:
                await asyncio.wait_for(asyncio.shield(event.wait()), timeout=wait_for)
            except TimeoutError:
                pass

    def cleanup(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)
        self._results.pop(approval_id, None)


_registry: ApprovalRegistry | None = None


def get_approval_registry() -> ApprovalRegistry:
    global _registry
    if _registry is None:
        _registry = ApprovalRegistry()
    return _registry


def reset_approval_registry() -> None:
    global _registry
    _registry = None
