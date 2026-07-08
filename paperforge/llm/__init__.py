"""LLM abstraction layer.

Supports multiple providers through a uniform async interface:
- `openai`: native OpenAI SDK (function calling)
- `anthropic`: native Anthropic SDK (tool use)
- `openai_compatible`: OpenAI-compatible APIs (Westlake, DeepSeek, etc.)
- `mock`: deterministic mock provider for testing
"""

from paperforge.llm.base import (
    ChatResponse,
    Chunk,
    LLMClient,
    Message,
    ToolCall,
    ToolDefinition,
)
from paperforge.llm.factory import get_llm_client

__all__ = [
    "LLMClient",
    "ChatResponse",
    "Chunk",
    "Message",
    "ToolCall",
    "ToolDefinition",
    "get_llm_client",
]
