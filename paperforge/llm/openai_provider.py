"""OpenAI provider using the native openai SDK.

Supports both OpenAI direct API and OpenAI-compatible APIs (via base_url).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

try:
    import httpx
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None  # type: ignore
    httpx = None  # type: ignore

from paperforge.llm.base import (
    ChatResponse,
    Chunk,
    LLMClient,
    Message,
    ToolCall,
    ToolDefinition,
)


class OpenAIProvider(LLMClient):
    """Async OpenAI provider with function calling."""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        default_model: str = "gpt-4o-mini",
    ) -> None:
        if AsyncOpenAI is None:
            raise ImportError(
                "openai package is required. Install with: pip install openai"
            )
        # ponytail: trust_env=False to bypass broken SSL_CERT_FILE (e.g. Anaconda's cacert.pem)
        # When trust_env=True (default), httpx uses SSL_CERT_FILE env var which may be outdated.
        # Bypassing uses httpx's bundled certifi instead.
        http_client = httpx.AsyncClient(trust_env=False) if httpx else None
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        self.default_model = default_model

    @staticmethod
    def _to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id,
                        "content": m.content or "",
                    }
                )
            elif m.role == "assistant" and m.tool_calls:
                result.append(
                    {
                        "role": "assistant",
                        "content": m.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.args, ensure_ascii=False),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                result.append({"role": m.role, "content": m.content or ""})
        return result

    @staticmethod
    def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
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
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
        if response_format:
            kwargs["response_format"] = response_format
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        resp = await self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, ValueError):
                    args = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, args=args)
                )
        return ChatResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
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
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        async for event in await self.client.chat.completions.create(**kwargs):
            if not event.choices:
                continue
            delta = event.choices[0].delta
            content = delta.content if hasattr(delta, "content") else None
            finish = event.choices[0].finish_reason
            yield Chunk(content=content, finish_reason=finish)
