"""Anthropic provider using the native anthropic SDK."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None  # type: ignore

from paperforge.llm.base import (
    ChatResponse,
    Chunk,
    LLMClient,
    Message,
    ToolCall,
    ToolDefinition,
)


class AnthropicProvider(LLMClient):
    """Async Anthropic provider with tool use."""

    def __init__(self, api_key: str, default_model: str = "claude-3-5-sonnet-latest") -> None:
        if AsyncAnthropic is None:
            raise ImportError(
                "anthropic package is required. Install with: pip install anthropic"
            )
        self.client = AsyncAnthropic(api_key=api_key)
        self.default_model = default_model

    def _split_messages(self, messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        """Convert to Anthropic format: system string + messages list."""
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content or "")
            elif m.role == "user":
                out.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
                if m.tool_calls:
                    content: list[dict[str, Any]] = []
                    if m.content:
                        content.append({"type": "text", "text": m.content})
                    for tc in m.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.args,
                            }
                        )
                    out.append({"role": "assistant", "content": content})
                else:
                    out.append({"role": "assistant", "content": m.content or ""})
            elif m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content or "",
                            }
                        ],
                    }
                )
        return "\n\n".join(system_parts), out

    @staticmethod
    def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        system, msgs = self._split_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "system": system,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        resp = await self.client.messages.create(**kwargs)
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, args=block.input)
                )
        return ChatResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=resp.stop_reason,
            raw=resp,
        )

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Chunk]:
        system, msgs = self._split_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "system": system,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield Chunk(content=text)
        yield Chunk(finish_reason="stop")
