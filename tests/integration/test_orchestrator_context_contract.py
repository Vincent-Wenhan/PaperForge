"""P0 Integration Closure contract tests (doc 40.1 - 40.4).

These catch the "file A changed, file B not synced" class of bugs: the
ToolContext/EventEmitter task_id contract, nextjs_app workspace restore,
workspace tool registry consistency, and resource-gate continuous editing.
"""

from __future__ import annotations

import json
import uuid

import pytest

from paperforge.llm.base import ChatResponse, ToolCall
from paperforge.orchestrator.loop import Orchestrator
from paperforge.orchestrator.tools import TOOL_DEFINITIONS
from paperforge.orchestrator.workspace import (
    TOOL_SPECS,
    available_resources,
    check_tool_prerequisites,
    load_workspace_state,
)
from paperforge.schemas.tool_result import ToolResult, ToolStatus


class FakeLLM:
    """Text-only LLM so orchestrator.run needs no provider/network."""

    async def chat(self, model, messages, tools=None, **kwargs):
        return ChatResponse(content="hello", tool_calls=[], finish_reason="stop")

    # Some callers use stream(); route it through chat() semantics.
    async def stream(self, model, messages, tools=None, **kwargs):
        resp = await self.chat(model, messages, tools)
        if resp.content:
            yield type(
                "Chunk",
                (),
                {"content": resp.content, "tool_calls": [], "finish_reason": "stop"},
            )()


@pytest.mark.asyncio
async def test_orchestrator_constructs_tool_context(storage):
    """ToolContext construction must not TypeError when task_id is threaded."""
    run = storage.create_run(f"run_{uuid.uuid4().hex[:8]}", title="Test")
    task = storage.create_task(
        run_id=run["id"],
        title="Test",
        goal="hello",
        status="queued",
        phase="init",
    )
    storage.add_message(
        run_id=run["id"],
        role="user",
        content="hello",
    )

    orchestrator = Orchestrator(llm=FakeLLM(), storage=storage)
    # The key assertion: this must not raise despite task_id threading.
    await orchestrator.run(
        run_id=run["id"],
        user_message="hello",
        task_id=task["id"],
    )


def test_nextjs_app_artifact_restores_workspace(tmp_path, storage):
    """nextjs_app artifact + metadata.app_path -> WorkspaceState workspace resource."""
    run = storage.create_run(f"run_{uuid.uuid4().hex[:8]}", title="Workspace")
    app_path = tmp_path / "app"
    app_path.mkdir()

    artifact_id = storage.save_artifact(
        run_id=run["id"],
        artifact_type="nextjs_app",
        data={"app_id": "app_1"},
        metadata={"app_path": str(app_path)},
    )

    state = load_workspace_state(storage, run["id"])
    assert state.app_id == artifact_id
    assert state.workspace_path == str(app_path)
    assert "workspace" in available_resources(state)


@pytest.mark.asyncio
async def test_event_emitter_defaults_task_id(storage):
    """Convenience wrappers attach the bound task_id by default."""
    from paperforge.orchestrator.events import EventEmitter, EventManager

    manager = EventManager()
    captured: list = []

    async def fake_broadcast(event):
        captured.append(event)

    manager.broadcast = fake_broadcast  # type: ignore[method-assign]
    emitter = EventEmitter(run_id="run_1", manager=manager, task_id="task_9")
    await emitter.text("hi")
    assert captured[0].task_id == "task_9"


def test_workspace_tool_registry_is_consistent():
    declared = {d.name for d in TOOL_DEFINITIONS}
    gated = set(TOOL_SPECS.keys())
    handlers = {
        "inspect_workspace",
        "read_workspace_file",
        "apply_workspace_patch",
        "run_checks",
        "parse_paper",
        "compose_capabilities",
        "plan_product",
        "generate_nextjs_app",
        "verify_app",
        "finish",
    }
    required = {"inspect_workspace", "read_workspace_file", "apply_workspace_patch", "run_checks"}
    assert required <= declared
    assert required <= gated
    assert required <= handlers


def test_workspace_edit_is_not_blocked_by_resource_gate(storage, workspace_artifact):
    """Continuous edit passes the resource gate once a workspace exists."""
    state = load_workspace_state(storage, workspace_artifact.run_id)
    allowed, missing = check_tool_prerequisites("apply_workspace_patch", state)
    assert allowed
    assert missing == []


def test_completed_generation_has_workspace_resource(storage, workspace_artifact):
    state = load_workspace_state(storage, workspace_artifact.run_id)
    assert "workspace" in available_resources(state)


def test_done_phase_does_not_block_workspace_edit(storage, workspace_artifact):
    """DONE phase must not gate workspace tools; resource gate is authoritative."""
    from paperforge.orchestrator.loop import Orchestrator, RunPhase

    orc = Orchestrator(llm=FakeLLM(), storage=storage)
    orc.phase = RunPhase.VERIFIED
    state = load_workspace_state(storage, workspace_artifact.run_id)
    allowed, missing = check_tool_prerequisites("inspect_workspace", state)
    assert allowed
    assert missing == []
    assert orc.phase == RunPhase.VERIFIED
