"""Factory for creating LLM clients based on configuration."""

from __future__ import annotations

from paperforge.config import get_config
from paperforge.llm.base import ChatResponse, LLMClient, Message
from paperforge.llm.mock_provider import MockLLMClient


class LocalTestLLM(MockLLMClient):
    """Scripted local test provider used by the no-mock Playwright E2E.

    Replies with a recognizable marker to the sent message so the browser
    test can assert the reply streamed in without a page refresh. This is a
    real backend (real SQLite + SSE), not a mocked /state route.
    """

    async def chat(self, model, messages, tools=None, response_format=None,
                   temperature=0.7, max_tokens=None) -> ChatResponse:
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        last = ""
        for m in reversed(messages):
            if m.role == "user" and m.content:
                last = m.content
                break
        if "stream-test" in last:
            return ChatResponse(
                content="stream-test-response for: " + last,
                finish_reason="stop",
            )
        return await super().chat(
            model, messages, tools, response_format, temperature, max_tokens
        )


def get_llm_client() -> LLMClient:
    """Return the configured LLM client. Defaults to mock provider."""
    cfg = get_config()
    provider = cfg.LLM_PROVIDER

    if provider == "mock":
        return MockLLMClient()

    if provider == "local_test":
        return LocalTestLLM()

    if provider == "openai":
        from paperforge.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=cfg.LLM_API_KEY,
            default_model=cfg.LLM_MODEL,
        )

    if provider == "anthropic":
        from paperforge.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=cfg.ANTHROPIC_API_KEY)

    if provider == "openai_compatible":
        from paperforge.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=cfg.LLM_API_KEY,
            base_url=cfg.LLM_BASE_URL or None,
            default_model=cfg.LLM_MODEL,
        )

    return MockLLMClient()
