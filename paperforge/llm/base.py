"""LLM client protocol and shared types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


class ToolCall:
    """A tool call produced by the LLM."""

    __slots__ = ("id", "name", "args")

    def __init__(self, id: str, name: str, args: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.args = args

    def __repr__(self) -> str:
        return f"ToolCall(id={self.id!r}, name={self.name!r}, args={self.args!r})"


class Message:
    """A chat message."""

    __slots__ = ("role", "content", "tool_calls", "tool_call_id", "name")

    def __init__(
        self,
        role: str,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> None:
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.name = name


class ToolDefinition:
    """A tool the LLM can call."""

    __slots__ = ("name", "description", "input_schema")

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema


class ChatResponse:
    """Response from a non-streaming chat call."""

    __slots__ = ("content", "tool_calls", "role", "finish_reason", "raw", "message_id")

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        role: str = "assistant",
        finish_reason: str | None = None,
        raw: Any = None,
        message_id: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.role = role
        self.finish_reason = finish_reason
        self.raw = raw
        self.message_id = message_id


class Chunk:
    """A streamed chunk from the LLM."""

    __slots__ = ("content", "tool_calls", "finish_reason")

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


@runtime_checkable
class LLMClient(Protocol):
    """Async LLM client protocol."""

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        ...

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Chunk]:
        ...
