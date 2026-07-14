from __future__ import annotations

import pytest

from paperforge.orchestrator.approvals import ApprovalRegistry
from paperforge.orchestrator.loop import ALLOWED_TOOLS, RunPhase


@pytest.mark.asyncio
async def test_approval_wait_reads_database_resolution(storage):
    storage.create_run("run_checkpoint", "Checkpoint", status="running")
    approval = storage.create_approval(
        "run_checkpoint",
        "generate_nextjs_app",
        {"prd_id": "prd_1"},
    )
    registry = ApprovalRegistry()
    registry.register(approval["id"])

    storage.resolve_approval(approval["id"], approved=True)

    assert await registry.wait_for_resolution(
        approval["id"],
        storage,
        timeout=0.5,
    ) is True


def test_failed_preview_can_retry_repair_and_restart():
    assert "verify_app" in ALLOWED_TOOLS[RunPhase.GENERATED]
    assert "build_and_repair" in ALLOWED_TOOLS[RunPhase.GENERATED]
    assert "run_in_sandbox" in ALLOWED_TOOLS[RunPhase.VERIFIED]
    assert "restart_sandbox" in ALLOWED_TOOLS[RunPhase.PREVIEW_READY]
    assert "stop_sandbox" in ALLOWED_TOOLS[RunPhase.PREVIEW_READY]
