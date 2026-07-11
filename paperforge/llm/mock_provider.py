"""Mock LLM client for testing without external API calls.

Strategy: examine the last user message. If it contains tool-call keywords,
return a canned tool call + follow-up message. Otherwise return a canned text.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from paperforge.llm.base import (
    ChatResponse,
    Chunk,
    LLMClient,
    Message,
    ToolCall,
    ToolDefinition,
)


class MockLLMClient(LLMClient):
    """Deterministic mock client. Returns predictable responses based on input."""

    def __init__(self, responses: list[ChatResponse] | None = None) -> None:
        self.responses = list(responses) if responses else []
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "response_format": response_format,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        return self._generate_response(messages, tools, response_format)

    async def stream(
        self,
        model: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Chunk]:
        resp = await self.chat(model, messages, tools, temperature=temperature, max_tokens=max_tokens)
        if resp.content:
            # split content into chunks
            text = resp.content
            size = max(1, len(text) // 5)
            for i in range(0, len(text), size):
                yield Chunk(content=text[i : i + size])
        if resp.tool_calls:
            yield Chunk(tool_calls=resp.tool_calls, finish_reason=resp.finish_reason or "stop")
        else:
            yield Chunk(finish_reason="stop")

    def _generate_response(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        response_format: dict[str, Any] | None,
    ) -> ChatResponse:
        """Generate a context-aware mock response."""
        last_user = ""
        for m in reversed(messages):
            if m.role == "user" and m.content:
                last_user = m.content
                break

        # If json_object requested, return a JSON response
        if response_format and response_format.get("type") == "json_object":
            return ChatResponse(
                content=json.dumps(
                    {
                        "paper_id": "mock_paper",
                        "title": "Mock Paper Title",
                        "method": "Mock method description for testing.",
                        "key_innovations": ["mock innovation 1", "mock innovation 2"],
                        "inputs": ["text"],
                        "outputs": ["text"],
                        "metrics": [],
                        "capability_category": "text_generation",
                        "reusable_components": ["mock component"],
                        "product_hints": ["mock product hint"],
                        "constraints": ["GPU recommended"],
                        "dependencies": ["PyTorch"],
                    },
                    ensure_ascii=False,
                ),
                finish_reason="stop",
            )

        # If tools available and user message mentions parsing/generating, emit a tool call
        if tools:
            tool_names = [t.name for t in tools]
            # Default: call the first tool if it seems relevant
            if "parse_paper" in tool_names and any(
                kw in last_user.lower() for kw in ["parse", "upload", "pdf", "论文"]
            ):
                return ChatResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="call_mock_1",
                            name="parse_paper",
                            args={"pdf_path": "mock_paper.pdf", "paper_id": "mock_paper"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            if "generate_nextjs_app" in tool_names and any(
                kw in last_user.lower() for kw in ["generate", "build", "create", "生成", "构建"]
            ):
                return ChatResponse(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="call_mock_2",
                            name="generate_nextjs_app",
                            args={"prd_id": "mock_prd", "output_dir": "generated_apps/mock_app"},
                        )
                    ],
                    finish_reason="tool_calls",
                )

        # Default: return a helpful message
        return ChatResponse(
            content=f"[Mock LLM] Received message ({len(last_user)} chars). Use parse_paper / generate_nextjs_app tools to proceed.",
            finish_reason="stop",
        )


class ScriptedLLMClient(LLMClient):
    """Returns canned responses in order. Useful for deterministic tests."""

    def __init__(self, scripts: list[ChatResponse]) -> None:
        self.scripts = list(scripts)
        self.call_count = 0

    async def chat(self, model, messages, tools=None, response_format=None,
                   temperature=0.7, max_tokens=None) -> ChatResponse:
        if self.call_count >= len(self.scripts):
            return ChatResponse(content="[Scripted LLM exhausted]", finish_reason="stop")
        resp = self.scripts[self.call_count]
        self.call_count += 1
        return resp

    async def stream(self, model, messages, tools=None, temperature=0.7, max_tokens=None) -> AsyncIterator[Chunk]:
        resp = await self.chat(model, messages, tools, temperature=temperature, max_tokens=max_tokens)
        if resp.content:
            yield Chunk(content=resp.content)
        yield Chunk(finish_reason="stop")
