"""Orchestrator consumes ProviderStreamEvent (doc 9 / 11 / Provider DoD)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from paperforge.llm.base import ProviderStreamEvent
from paperforge.llm.mock_provider import MockLLMClient
from paperforge.orchestrator.loop import Orchestrator


class EventStreamingLLM(MockLLMClient):
    """Emits text chunks + a tool_done as ProviderStreamEvents (not Chunks)."""

    async def stream_events(
        self, model, messages, tools=None
    ) -> AsyncIterator[ProviderStreamEvent]:
        yield ProviderStreamEvent(kind="text_delta", text="Initial ")
        yield ProviderStreamEvent(kind="text_delta", text="answer")
        yield ProviderStreamEvent(
            kind="tool_done",
            tool_call_id="call_1",
            tool_name="some_tool",
            arguments={"a": 1},
        )
        yield ProviderStreamEvent(kind="done", finish_reason="stop")


class DummyEmitter:
    async def message_started(self, *a, **k):
        pass

    async def message_delta(self, *a, **k):
        pass

    async def message_completed(self, *a, **k):
        pass

    async def message_failed(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_orchestrator_streams_provider_events_and_preserves_tool_calls(storage):
    storage.create_run("run_pv", "Provider Stream Test")
    storage.add_message(run_id="run_pv", role="user", content="Hello")

    llm = EventStreamingLLM()
    orc = Orchestrator(llm=llm, storage=storage)
    result = await orc._stream_llm("model-x", [], None, DummyEmitter(), "run_pv")

    # The orchestrator saw tool_done -> ToolCall, plus preserved text.
    assert result.content is not None and "Initial" in result.content and "answer" in result.content
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "some_tool"
    assert result.tool_calls[0].args == {"a": 1}
    assert result.finish_reason == "stop"
