"""Tests for the MockLLMClient."""

from __future__ import annotations

import asyncio
import json

from paperforge.llm.base import Message
from paperforge.llm.mock_provider import MockLLMClient


def test_chat_with_json_response_format():
    client = MockLLMClient()
    response = asyncio.run(
        client.chat(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="test")],
            response_format={"type": "json_object"},
        )
    )
    data = json.loads(response.content)
    assert data["paper_id"] == "mock_paper"


def test_chat_returns_text_by_default():
    client = MockLLMClient()
    response = asyncio.run(
        client.chat(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="Hello, LLM!")],
        )
    )
    assert response.content is not None
    assert "Mock LLM" in response.content


def test_stream_yields_chunks():
    client = MockLLMClient()
    chunks = []

    async def collect():
        async for chunk in client.stream(
            model="gpt-4o-mini",
            messages=[Message(role="user", content="Hello")],
        ):
            chunks.append(chunk)

    asyncio.run(collect())
    assert len(chunks) >= 1
