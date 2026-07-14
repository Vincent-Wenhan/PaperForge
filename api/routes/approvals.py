"""Approvals API routes for HITL flow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.approvals import get_approval_registry
from paperforge.storage.db import get_storage

router = APIRouter()


class ApprovalResolve(BaseModel):
    approved: bool


class ApprovalView(BaseModel):
    approval_id: str
    id: str
    run_id: str
    tool: str
    tool_name: str
    args: dict
    status: str
    created_at: str
    resolved_at: str | None = None


def _to_approval(row: dict) -> ApprovalView:
    return ApprovalView(
        approval_id=row["id"],
        id=row["id"],
        run_id=row["run_id"],
        tool=row["tool_name"],
        tool_name=row["tool_name"],
        args=row.get("args") or {},
        status=row["status"],
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
    )


@router.get("", response_model=list[ApprovalView])
async def list_approvals(
    run_id: str | None = None,
    status: str | None = None,
) -> list[ApprovalView]:
    """List durable approvals for hydration and refresh recovery."""
    storage = get_storage()
    return [
        _to_approval(row)
        for row in storage.list_approvals(run_id=run_id, status=status)
    ]


@router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, req: ApprovalResolve) -> dict:
    """Resolve a pending approval."""
    storage = get_storage()
    approval = storage.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already {approval['status']}")

    resolved = storage.resolve_approval(approval_id, req.approved)
    if resolved is None:
        raise HTTPException(status_code=409, detail="Approval was already resolved")

    registry = get_approval_registry()
    registry.resolve(approval_id, req.approved)

    return _to_approval(resolved).model_dump()
