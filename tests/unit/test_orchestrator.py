"""Tests for the orchestrator loop."""

from __future__ import annotations

import pytest

from paperforge.orchestrator.events import get_event_manager
from paperforge.orchestrator.loop import Orchestrator
from paperforge.llm.base import ChatResponse, Message, ToolCall
from paperforge.llm.mock_provider import MockLLMClient


@pytest.mark.asyncio
async def test_orchestrator_runs_to_completion(storage):
    """Orchestrator should run and finish."""
    storage.create_run("run_orc", "Orchestrator Test")

    class StopLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            return ChatResponse(content="Done!", finish_reason="stop")

    # API layer saves the user message; orchestrator must not duplicate it.
    storage.add_message(run_id="run_orc", role="user", content="Hello")

    orc = Orchestrator(llm=StopLLM(), storage=storage)
    await orc.run(run_id="run_orc", user_message="Hello")

    messages = storage.list_messages("run_orc")
    # Should have user + assistant messages
    assert len(messages) >= 2


@pytest.mark.asyncio
async def test_orchestrator_handles_tool_calls(storage):
    """Orchestrator should execute tool calls and continue."""
    storage.create_run("run_tool", "Tool Test")

    # API layer saves the user message; orchestrator must not duplicate it.
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
async def test_orchestrator_handles_tool_calls(storage):
    """Orchestrator should execute tool calls and continue."""
    storage.create_run("run_tool", "Tool Test")

    class ToolLLM:
        def __init__(self):
            self.call_count = 0

        async def chat(self, model, messages, tools=None, response_format=None,
                      temperature=0.7, max_tokens=None):
            self.call_count += 1
            if self.call_count == 1:
                return ChatResponse(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="finish",
                                        args={"summary": "All done"})],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="All done!", finish_reason="stop")

        async def stream(self, *args, **kwargs):
            yield None

    orc = Orchestrator(llm=ToolLLM(), storage=storage)
    await orc.run(run_id="run_tool", user_message="Finish the task")

    messages = storage.list_messages("run_tool")
    assert len(messages) >= 2
