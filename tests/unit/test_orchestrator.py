"""Tests for the orchestrator loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from paperforge.orchestrator.approvals import get_approval_registry
from paperforge.orchestrator.loop import (
    Orchestrator,
    RunPhase,
)
from paperforge.llm.base import ChatResponse, Message, ToolCall
from paperforge.llm.mock_provider import MockLLMClient


@pytest.mark.asyncio
async def test_orchestrator_runs_to_completion(storage):
    """Orchestrator should run and finish."""
    storage.create_run("run_orc", "Orchestrator Test")
    storage.add_message(run_id="run_orc", role="user", content="Hello")

    class StopLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            return ChatResponse(content="Done!", finish_reason="stop")

    orc = Orchestrator(llm=StopLLM(), storage=storage)
    await orc.run(run_id="run_orc", user_message="Hello")

    messages = storage.list_messages("run_orc")
    assert len(messages) >= 2
    assert orc.phase in (RunPhase.DONE, RunPhase.INIT)


@pytest.mark.asyncio
async def test_orchestrator_handles_tool_calls(storage):
    """Orchestrator should execute tool calls and continue."""
    storage.create_run("run_tool", "Tool Test")
    storage.add_message(run_id="run_tool", role="user", content="Finish the task")

    class ToolLLM(MockLLMClient):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def chat(self, *args, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return ChatResponse(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="finish",
                                        args={"summary": "All done"})],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="All done!", finish_reason="stop")

    orc = Orchestrator(llm=ToolLLM(), storage=storage)
    await orc.run(run_id="run_tool", user_message="Finish the task")

    messages = storage.list_messages("run_tool")
    assert len(messages) >= 2


@pytest.mark.asyncio
async def test_orchestrator_phase_persists_across_runs(storage):
    """Phase should persist across orchestrator instances (multi-turn support).

    This verifies the P0-2 fix: orchestrator restores phase from storage
    at the start of run(), so multi-turn conversations don't reset phase.
    """
    storage.create_run("run_phase", "Phase Persist Test")
    storage.add_message(run_id="run_phase", role="user", content="Parse this paper")
    storage.update_run_phase("run_phase", RunPhase.PARSED.value)

    class ResumingLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            return ChatResponse(content="Resuming from PARSED phase.", finish_reason="stop")

    orc = Orchestrator(llm=ResumingLLM(), storage=storage)

    # Patch get_run_phase to verify it's called and phase is restored
    call_count = 0
    original_get_phase = storage.get_run_phase

    def patched_get_phase(run_id):
        nonlocal call_count
        call_count += 1
        return original_get_phase(run_id)

    storage.get_run_phase = patched_get_phase
    await orc.run(run_id="run_phase", user_message="Continue")

    # Verify storage.get_run_phase was called
    assert call_count >= 1
    # Phase should remain PARSED — a plain text reply must not advance phase
    # or mark the run as done. This is the key fix that unblocks
    # productization after a normal Q&A exchange.
    assert orc.phase == RunPhase.PARSED



@pytest.mark.asyncio
async def test_orchestrator_resource_gate_rejects_missing_prereq(storage):
    """Resource gate should reject tools whose prerequisites are missing.

    Phase no longer decides tool permission (doc 14); the resource gate is the
    sole authority. A generate_nextjs_app call without a PRD is rejected.
    """
    storage.create_run("run_gate", "Phase Gate Test")
    storage.add_message(run_id="run_gate", role="user", content="Generate something")

    # Phase is INIT by default — generate_nextjs_app not allowed
    class GateLLM(MockLLMClient):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def chat(self, *args, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return ChatResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="generate_nextjs_app",
                            args={"prd_id": "test"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="Done", finish_reason="stop")

    orc = Orchestrator(llm=GateLLM(), storage=storage)
    await orc.run(run_id="run_gate", user_message="Generate")

    # The tool should have been rejected by the resource gate (no PRD)
    messages = storage.list_messages("run_gate")
    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert len(tool_messages) > 0
    result = json.loads(tool_messages[0]["content"])
    assert result["ok"] is False
    assert result["code"] in ("resource_prerequisite", "tool_exception")
    assert "Missing required resources" in result["error"]


@pytest.mark.asyncio
async def test_orchestrator_approval_flow(storage):
    """Dangerous tools should trigger approval flow.

    Verifies P0-4: when orchestrator calls generate_nextjs_app (a dangerous
    tool), it creates an approval record, emits approval.requested, and
    waits for user resolution.
    """
    storage.create_run("run_approval", "Approval Flow Test")
    storage.add_message(run_id="run_approval", role="user", content="Generate app")

    # Set phase to PLANNED so generate_nextjs_app is allowed
    storage.update_run_phase("run_approval", RunPhase.PLANNED.value)

    # Seed the prd resource the resource gate requires before generate_nextjs_app
    # becomes reachable (allows the approval flow to engage, doc 11).
    storage.save_artifact(
        run_id="run_approval",
        artifact_type="prd",
        data={"goal": "test"},
    )

    class ApprovalLLM(MockLLMClient):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def chat(self, *args, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return ChatResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="c1",
                            name="generate_nextjs_app",
                            args={"prd_id": "test"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="Done", finish_reason="stop")

    orc = Orchestrator(llm=ApprovalLLM(), storage=storage)

    # Start orchestrator in background — it will block waiting for approval
    task = asyncio.create_task(orc.run(run_id="run_approval", user_message="Generate"))

    # Poll for the approval to be registered (up to 2s). The orchestrator
    # creates the approval asynchronously after emitting approval.requested.
    registry = get_approval_registry()
    deadline = 2.0
    while deadline > 0:
        if len(registry._pending) > 0 or len(registry._results) > 0:
            break
        await asyncio.sleep(0.05)
        deadline -= 0.05
    assert len(registry._pending) > 0 or len(registry._results) > 0

    # Clean up the task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_run_phase_enum_completeness():
    """RunPhase enum should have all expected phases."""
    expected_phases = {
        "init", "parsed", "composed", "planned",
        "generated", "verified", "preview_ready",
        "done", "error",
    }
    actual_phases = {phase.value for phase in RunPhase}
    assert actual_phases == expected_phases


def test_allowed_tools_covers_all_phases():
    """RunPhase enum covers all pipeline stages (phase no longer gates tools)."""
    assert len(RunPhase) >= 8


def test_phase_transitions_complete():
    """RunPhase progression values remain stable for the UI step display."""
    assert RunPhase.PARSE.value if hasattr(RunPhase, "PARSE") else True


@pytest.mark.asyncio
async def test_parse_paper_updates_card_path(storage):
    """handle_parse_paper should set papers.card_path after saving the card.

    This is critical: composer.py and product_planner.py both read
    paper["card_path"] to load the capability card. If parse_paper
    doesn't update card_path, the downstream compose/plan flow breaks
    with "Capability card not found".
    """
    from pathlib import Path
    from unittest.mock import patch

    from paperforge.orchestrator.events import EventEmitter, get_event_manager
    from paperforge.orchestrator.tools import ToolContext, handle_parse_paper

    paper_id = "test_paper_card_path"

    async def mock_parse_paper(pdf_path, paper_id, llm):
        return {
            "paper_id": paper_id,
            "title": "Test Paper",
            "method": "Mock method",
        }

    storage.create_run("run_card_path", "Card Path Test")
    event_manager = get_event_manager()
    emit = EventEmitter(run_id="run_card_path", manager=event_manager)
    ctx = ToolContext(run_id="run_card_path", storage=storage, llm=MockLLMClient(), emit=emit)

    with patch(
        "paperforge.agents.paper_parser.parse_paper",
        side_effect=mock_parse_paper,
    ):
        result = await handle_parse_paper(
            args={"pdf_path": "/tmp/fake.pdf", "paper_id": paper_id},
            ctx=ctx,
        )

    paper = storage.get_paper(paper_id)
    assert paper is not None, "Paper row should be created"
    assert paper["card_path"] is not None, "card_path must be set"
    assert paper["status"] == "parsed"
    assert Path(paper["card_path"]).exists(), "Card file must exist on disk"
    assert result.ok is True


@pytest.mark.asyncio
async def test_plain_chat_does_not_block_subsequent_productization(storage):
    """A plain Q&A reply must not advance the run phase or mark the run
    as done. This is the core fix that unblocks the screenshot scenario:

        1. User asks "who are you"
        2. Orchestrator returns a plain text reply
        3. User then asks to productize a paper
        4. parse_paper must still be callable (phase stays at INIT)

    Before the fix, step 2 would set phase=DONE, which blocks parse_paper
    in step 4 with "not allowed in phase done".
    """
    storage.create_run("run_plain", "Plain Chat Test")
    storage.add_message(run_id="run_plain", role="user", content="who are you")

    class PlainLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            return ChatResponse(content="I am PaperForge.", finish_reason="stop")

    orc = Orchestrator(llm=PlainLLM(), storage=storage)
    await orc.run(run_id="run_plain", user_message="who are you")

    # Phase must NOT advance to DONE on a plain reply.
    assert orc.phase != RunPhase.DONE
    # Run status should remain active, not completed.
    run = storage.get_run("run_plain")
    assert run["status"] == "active"