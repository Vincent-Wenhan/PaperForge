"""Self-check for resource-gate + step + claim logic (ponytail leave-behind)."""

from __future__ import annotations

from paperforge.orchestrator.workspace import (
    WorkspaceState,
    available_resources,
    check_tool_prerequisites,
)


def demo() -> None:
    empty = WorkspaceState()
    allowed, missing = check_tool_prerequisites("generate_nextjs_app", empty)
    assert not allowed and "prd" in missing, "no prd -> must be blocked"

    with_prd = WorkspaceState(prd_id="prd_1")
    allowed, missing = check_tool_prerequisites("generate_nextjs_app", with_prd)
    assert allowed and not missing, "prd present -> allowed"

    assert "workspace" not in available_resources(with_prd)
    assert "prd" in available_resources(with_prd)
    print("resource-gate ok")


if __name__ == "__main__":
    demo()
