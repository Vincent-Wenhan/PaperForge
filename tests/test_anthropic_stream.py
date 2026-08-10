"""Anthropic provider streaming tool-call regression (doc 7 / 40.5)."""

from __future__ import annotations

import pytest

from paperforge.llm.base import ChatResponse, Chunk, ToolCall, ToolDefinition


@pytest.mark.asyncio
async def test_anthropic_stream_preserves_tool_calls(monkeypatch):
    from paperforge.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider.__new__(AnthropicProvider)

    response = ChatResponse(
        content="I will inspect the workspace.",
        tool_calls=[
            ToolCall(id="call_1", name="inspect_workspace", args={})
        ],
        finish_reason="tool_use",
    )

    async def fake_chat(*args, **kwargs):
        return response

    monkeypatch.setattr(provider, "chat", fake_chat)

    chunks = [
        chunk
        async for chunk in provider.stream(
            model="test",
            messages=[],
            tools=[ToolDefinition(name="inspect_workspace", description="x", input_schema={"type": "object"})],
        )
    ]

    calls = [call for chunk in chunks for call in (chunk.tool_calls or [])]
    assert [call.name for call in calls] == ["inspect_workspace"]

    assert any(isinstance(c, Chunk) and c.finish_reason == "tool_use" for c in chunks)
