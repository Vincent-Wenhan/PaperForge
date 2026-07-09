"""Orchestrator main loop.

Implements the agentic loop: LLM → tool → LLM, until LLM stops calling tools.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message, ToolCall
from paperforge.llm.factory import get_llm_client
from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.tools import TOOL_DEFINITIONS, ToolContext, dispatch_tool
from paperforge.prompts import load_prompt
from paperforge.storage.db import Storage, get_storage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 1.0  # seconds


class Orchestrator:
    """Main orchestrator that runs the agentic loop."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.storage = storage or get_storage()

    async def run(self, run_id: str, user_message: str) -> None:
        """Run the orchestrator loop for a single user message."""
        cfg = get_config()
        event_manager = get_event_manager()
        emit = EventEmitter(run_id=run_id, manager=event_manager)

        await emit.run_started()

        # Load orchestrator system prompt
        system_prompt = load_prompt("orchestrator")

        # Load history from storage
        history = self.storage.list_messages(run_id)

        # Build message list with system prompt first
        messages: list[Message] = [Message(role="system", content=system_prompt)]

        for h in history:
            if h["role"] == "user":
                messages.append(Message(role="user", content=h["content"]))
            elif h["role"] == "assistant":
                tool_calls = h.get("tool_calls") or []
                messages.append(
                    Message(
                        role="assistant",
                        content=h["content"],
                        tool_calls=[ToolCall(id=tc.get("id", ""), name=tc.get("name", ""), args=tc.get("args", {})) for tc in tool_calls],
                    )
                )
            elif h["role"] == "tool":
                messages.append(
                    Message(role="tool", content=h["content"], tool_call_id=h.get("tool_call_id") or "")
                )

        # Add the new user message
        messages.append(Message(role="user", content=user_message))

        # Save the user message
        self.storage.add_message(
            run_id=run_id,
            role="user",
            content=user_message,
        )

        # Build context for tool dispatch
        ctx = ToolContext(
            run_id=run_id,
            storage=self.storage,
            llm=self.llm,
            emit=emit,
        )

        # Main loop
        iterations = 0
        try:
            while iterations < MAX_ITERATIONS:
                iterations += 1
                logger.info(f"Orchestrator iteration {iterations} for run {run_id}")

                # LLM call with retry on transient failures
                response = await self._call_llm_with_retry(
                    model=cfg.ORCHESTRATOR_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    emit=emit,
                )
                if response is None:
                    return  # error already emitted

                if response.tool_calls:
                    # Save assistant message with tool_calls
                    self.storage.add_message(
                        run_id=run_id,
                        role="assistant",
                        content=response.content or "",
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "args": tc.args}
                            for tc in response.tool_calls
                        ],
                    )
                    messages.append(
                        Message(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )

                    # Execute each tool call
                    for call in response.tool_calls:
                        await emit.tool_call(call)

                        # Dispatch tool
                        result = await dispatch_tool(call.name, call.args, ctx)

                        # Save tool result message
                        self.storage.add_message(
                            run_id=run_id,
                            role="tool",
                            content=result,
                            tool_call_id=call.id,
                            name=call.name,
                        )

                        await emit.tool_result(call.name, result, call.id)

                        # Add to messages
                        messages.append(
                            Message(
                                role="tool",
                                content=result,
                                tool_call_id=call.id,
                                name=call.name,
                            )
                        )

                    # Loop back to LLM
                    continue

                # LLM returned text (no tool calls)
                final_content = response.content or ""
                self.storage.add_message(
                    run_id=run_id,
                    role="assistant",
                    content=final_content,
                )

                await emit.text(final_content)
                await emit.run_finished()
                return

            # Max iterations reached
            logger.warning(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
            await emit.run_error(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")

        except Exception as e:
            logger.exception(f"Orchestrator error: {e}")
            await emit.run_error(str(e))

    async def _call_llm_with_retry(
        self,
        model: str,
        messages: list[Message],
        tools: list[Any],
        emit: EventEmitter,
    ) -> Any:
        """Call LLM with exponential backoff retry. Returns None if all retries failed."""
        last_error: Exception | None = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                return await self.llm.chat(
                    model=model,
                    messages=messages,
                    tools=tools,
                )
            except Exception as e:
                last_error = e
                logger.warning(f"LLM call attempt {attempt}/{LLM_MAX_RETRIES} failed: {e}")
                if attempt < LLM_MAX_RETRIES:
                    delay = LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                else:
                    await emit.run_error(f"LLM call failed after {LLM_MAX_RETRIES} retries: {last_error}")
                    return None
        return None
