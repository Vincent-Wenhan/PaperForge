"""Factory for creating LLM clients based on configuration."""

from __future__ import annotations

from paperforge.config import get_config
from paperforge.llm.base import LLMClient
from paperforge.llm.mock_provider import MockLLMClient


def get_llm_client() -> LLMClient:
    """Return the configured LLM client. Defaults to mock provider."""
    cfg = get_config()
    provider = cfg.LLM_PROVIDER

    if provider == "mock":
        return MockLLMClient()

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
