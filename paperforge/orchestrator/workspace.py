"""WorkspaceState, ToolSpec and resource gating (doc 10.4 / 11).

Replaces the global phase gate as the authoritative tool-permission check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class WorkspaceState:
    paper_ids: list[str] = field(default_factory=list)
    capability_card_ids: list[str] = field(default_factory=list)
    composition_id: str | None = None
    prd_id: str | None = None
    app_id: str | None = None
    workspace_path: str | None = None
    revision_id: str | None = None
    verification_report_id: str | None = None
    sandbox_id: str | None = None
    preview_url: str | None = None


ToolRisk = Literal["read", "workspace_write", "sandbox_exec", "network", "destructive"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    requires: frozenset[str] = field(default_factory=frozenset)
    produces: frozenset[str] = field(default_factory=frozenset)
    risk: ToolRisk = "read"


TOOL_SPECS: dict[str, ToolSpec] = {
    "parse_paper": ToolSpec(
        name="parse_paper",
        requires=frozenset({"paper"}),
        produces=frozenset({"capability_card"}),
        risk="read",
    ),
    "compose_capabilities": ToolSpec(
        name="compose_capabilities",
        requires=frozenset({"capability_card"}),
        produces=frozenset({"composition"}),
        risk="read",
    ),
    "plan_product": ToolSpec(
        name="plan_product",
        requires=frozenset({"capability_card"}),
        produces=frozenset({"prd"}),
        risk="read",
    ),
    "generate_nextjs_app": ToolSpec(
        name="generate_nextjs_app",
        requires=frozenset({"prd"}),
        produces=frozenset({"workspace"}),
        risk="workspace_write",
    ),
    "inspect_workspace": ToolSpec(
        name="inspect_workspace",
        requires=frozenset({"workspace"}),
        risk="read",
    ),
    "read_workspace_file": ToolSpec(
        name="read_workspace_file",
        requires=frozenset({"workspace"}),
        risk="read",
    ),
    "apply_workspace_patch": ToolSpec(
        name="apply_workspace_patch",
        requires=frozenset({"workspace"}),
        produces=frozenset({"workspace_modified"}),
        risk="workspace_write",
    ),
    "run_checks": ToolSpec(
        name="run_checks",
        requires=frozenset({"workspace"}),
        risk="sandbox_exec",
    ),
    "start_preview": ToolSpec(
        name="start_preview",
        requires=frozenset({"workspace"}),
        produces=frozenset({"sandbox"}),
        risk="sandbox_exec",
    ),
}

def available_resources(state: WorkspaceState) -> set[str]:
    resources: set[str] = set()
    if state.paper_ids:
        resources.add("paper")
    if state.capability_card_ids:
        resources.add("capability_card")
    if state.composition_id:
        resources.add("composition")
    if state.prd_id:
        resources.add("prd")
    if state.workspace_path:
        resources.add("workspace")
    if state.sandbox_id:
        resources.add("sandbox")
    return resources


def load_workspace_state(storage, run_id: str) -> WorkspaceState:
    """Rebuild WorkspaceState from durable storage for a run."""
    papers = storage.list_run_papers(run_id)
    paper_ids = [p["paper_id"] for p in papers]

    state = WorkspaceState(paper_ids=paper_ids)

    # capability cards produced for run's papers
    card_ids: list[str] = []
    for pid in paper_ids:
        paper = storage.get_paper(pid) if hasattr(storage, "get_paper") else None
        if paper and paper.get("card_path"):
            card_ids.append(pid)
    state.capability_card_ids = card_ids

    # composition / prd / workspace / sandbox from artifacts
    artifacts = storage.list_artifacts(run_id) if hasattr(storage, "list_artifacts") else []
    for art in artifacts:
        atype = art.get("type", "")
        metadata = art.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                import json as _json

                metadata = _json.loads(metadata)
            except Exception:
                metadata = {}
        if atype == "composition":
            state.composition_id = art["id"]
        if atype == "prd":
            state.prd_id = art["id"]
        if atype in {"app", "workspace", "nextjs_app"}:
            state.workspace_path = (
                metadata.get("app_path")
                or metadata.get("workspace_path")
                or art.get("path")
            )
            state.app_id = art["id"]
        if atype in {"verification_report", "verification"}:
            state.verification_report_id = art["id"]

    latest_sandbox = (
        storage.get_latest_sandbox_for_run(run_id)
        if hasattr(storage, "get_latest_sandbox_for_run")
        else None
    )
    if latest_sandbox and (latest_sandbox.get("status") != "stopped"):
        state.sandbox_id = latest_sandbox["id"]
        state.preview_url = latest_sandbox.get("preview_url")

    return state


def check_tool_prerequisites(
    tool_name: str,
    state: WorkspaceState,
) -> tuple[bool, list[str]]:
    spec = TOOL_SPECS.get(tool_name)
    if spec is None:
        # Unknown tools aren't gated by resources (read-only default).
        return True, []
    missing = sorted(spec.requires - available_resources(state))
    return len(missing) == 0, missing
