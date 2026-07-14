from __future__ import annotations

from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.tools import TOOL_DEFINITIONS, ToolContext


def test_recovery_tools_are_declared():
    names = {definition.name for definition in TOOL_DEFINITIONS}
    assert {"build_and_repair", "restart_sandbox", "stop_sandbox"} <= names


def test_tool_context_reuses_one_sandbox_manager(storage, mock_llm):
    storage.create_run("run_context", "Context", status="active")
    emit = EventEmitter("run_context", get_event_manager())
    ctx = ToolContext("run_context", storage, mock_llm, emit)

    first = ctx.get_sandbox_manager()
    second = ctx.get_sandbox_manager()

    assert first is second
