"""Approvals API routes for HITL flow."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.approvals import get_approval_registry
from paperforge.storage.db import get_storage

router = APIRouter()


class ApprovalResolve(BaseModel):
    approved: bool


@router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, req: ApprovalResolve) -> dict:
    """Resolve a pending approval."""
    storage = get_storage()
    approval = storage.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already {approval['status']}")

    storage.resolve_approval(approval_id, req.approved)

    registry = get_approval_registry()
    registry.resolve(approval_id, req.approved)

    return {"approval_id": approval_id, "approved": req.approved}
