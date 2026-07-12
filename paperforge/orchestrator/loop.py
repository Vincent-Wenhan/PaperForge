"""Orchestrator main loop.

Implements the agentic loop: LLM → tool → LLM, until LLM stops calling tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from enum import Enum
from typing import Any

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message, ToolCall
from paperforge.llm.factory import get_llm_client
from paperforge.orchestrator.approvals import get_approval_registry
from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.tools import TOOL_DEFINITIONS, ToolContext, dispatch_tool
from paperforge.prompts import load_prompt
from paperforge.storage.db import Storage, get_storage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 1.0  # seconds
APPROVAL_TIMEOUT = 300  # 5 minutes

# Tools that require explicit user approval before execution (HITL).
DANGEROUS_TOOLS = {"generate_nextjs_app", "run_in_sandbox"}


class RunPhase(str, Enum):
    """Deterministic phase gate for orchestrator flow."""

    INIT = "init"
    PARSED = "parsed"
    COMPOSED = "composed"
    PLANNED = "planned"
    GENERATED = "generated"
    VERIFIED = "verified"
    PREVIEW_READY = "preview_ready"
    DONE = "done"
    ERROR = "error"


# Tools allowed per phase. Tools not in the current phase's set are rejected.
ALLOWED_TOOLS: dict[RunPhase, set[str]] = {
    RunPhase.INIT: {"parse_paper", "finish"},
    RunPhase.PARSED: {"compose_capabilities", "plan_product", "finish"},
    RunPhase.COMPOSED: {"plan_product", "finish"},
    RunPhase.PLANNED: {"generate_nextjs_app", "finish"},
    RunPhase.GENERATED: {"verify_app", "finish"},
    RunPhase.VERIFIED: {"run_in_sandbox", "finish"},
    RunPhase.PREVIEW_READY: {"finish"},
    RunPhase.DONE: set(),
    RunPhase.ERROR: set(),
}


# Mapping tool name → next phase on success.
PHASE_TRANSITIONS: dict[str, RunPhase] = {
    "parse_paper": RunPhase.PARSED,
    "compose_capabilities": RunPhase.COMPOSED,
    "plan_product": RunPhase.PLANNED,
    "generate_nextjs_app": RunPhase.GENERATED,
    "verify_app": RunPhase.VERIFIED,
    "run_in_sandbox": RunPhase.PREVIEW_READY,
}


class Orchestrator:
    """Main orchestrator that runs the agentic loop."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        storage: Storage | None = None,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.storage = storage or get_storage()
        self.phase: RunPhase = RunPhase.INIT

    async def run(self, run_id: str, user_message: str) -> None:
        """Run the orchestrator loop for a single user message."""
        cfg = get_config()
        event_manager = get_event_manager()
        emit = EventEmitter(run_id=run_id, manager=event_manager)

        # Persist run status as running
        self.storage.update_run_status(run_id, "running")

        # Restore phase from storage (default to INIT if missing)
        stored_phase = self.storage.get_run_phase(run_id) or "init"
        try:
            self.phase = RunPhase(stored_phase)
        except ValueError:
            self.phase = RunPhase.INIT

        await emit.run_started()

        # Load orchestrator system prompt
        system_prompt = load_prompt("orchestrator")

        # API layer saves the user message; orchestrator must not duplicate it.

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
                logger.info(f"Orchestrator iteration {iterations} for run {run_id} (phase={self.phase.value})")

                # LLM call with retry on transient failures
                response = await self._call_llm_with_retry(
                    model=cfg.ORCHESTRATOR_MODEL,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    emit=emit,
                )
                if response is None:
                    # LLM failed; mark run as error so it doesn't stay "running".
                    self.phase = RunPhase.ERROR
                    self.storage.update_run_phase(run_id, self.phase.value)
                    self.storage.update_run_status(run_id, "error")
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

                        result = await self._execute_tool_call(call, ctx, emit, run_id)

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

                        # Phase transition only on successful tool execution.
                        # Parse the ToolResult envelope to check `ok`.
                        if call.name in PHASE_TRANSITIONS:
                            try:
                                parsed = json.loads(result)
                                ok = parsed.get("ok", False) if isinstance(parsed, dict) else False
                            except (json.JSONDecodeError, TypeError):
                                ok = False

                            if ok:
                                self.phase = PHASE_TRANSITIONS[call.name]
                                self.storage.update_run_phase(run_id, self.phase.value)

                    # Loop back to LLM
                    continue

                # LLM returned text (no tool calls): message lifecycle is
                # handled inside _stream_llm (message.started → message.delta
                # → message.completed). Here we persist the final message and
                # keep the run active so the user can continue the conversation.
                final_content = response.content or ""
                self.storage.add_message(
                    run_id=run_id,
                    role="assistant",
                    content=final_content,
                )
                self.storage.update_run_status(run_id, "active")
                await emit.run_finished()
                return

            # Max iterations reached
            logger.warning(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
            await emit.run_error(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
            self.phase = RunPhase.ERROR
            self.storage.update_run_phase(run_id, self.phase.value)
            self.storage.update_run_status(run_id, "error")

        except Exception as e:
            logger.exception(f"Orchestrator error: {e}")
            await emit.run_error(str(e))
            self.phase = RunPhase.ERROR
            self.storage.update_run_phase(run_id, self.phase.value)
            self.storage.update_run_status(run_id, "error")

    async def _execute_tool_call(
        self,
        call: ToolCall,
        ctx: ToolContext,
        emit: EventEmitter,
        run_id: str,
    ) -> str:
        """Execute a single tool call, applying phase gate and HITL approval."""
        # Phase gate: reject tools not allowed in the current phase.
        if call.name not in ALLOWED_TOOLS.get(self.phase, set()):
            return json.dumps({
                "ok": False,
                "tool": call.name,
                "error": f"Tool '{call.name}' is not allowed in phase '{self.phase.value}'.",
                "allowed_tools": sorted(ALLOWED_TOOLS.get(self.phase, set())),
                "current_phase": self.phase.value,
            }, ensure_ascii=False)

        # HITL: dangerous tools require user approval
        if call.name in DANGEROUS_TOOLS:
            approval = self.storage.create_approval(
                run_id=run_id,
                tool_name=call.name,
                args=call.args,
            )
            approval_id = approval["id"]

            registry = get_approval_registry()
            wait_event = registry.register(approval_id)

            await emit.approval_requested(
                approval_id=approval_id,
                tool_name=call.name,
                args=call.args,
            )

            try:
                await asyncio.wait_for(wait_event.wait(), timeout=APPROVAL_TIMEOUT)
            except asyncio.TimeoutError:
                registry.cleanup(approval_id)
                return json.dumps({
                    "ok": False,
                    "tool": call.name,
                    "error": f"Approval timed out after {APPROVAL_TIMEOUT}s.",
                }, ensure_ascii=False)

            approved = registry.get_result(approval_id) or False
            registry.cleanup(approval_id)

            await emit.approval_resolved(
                approval_id=approval_id,
                approved=approved,
                tool_name=call.name,
            )

            if not approved:
                return json.dumps({
                    "ok": False,
                    "tool": call.name,
                    "error": f"Tool {call.name} was rejected by the user.",
                }, ensure_ascii=False)

        # Dispatch tool
        return await dispatch_tool(call.name, call.args, ctx)

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
                return await self._stream_llm(model, messages, tools, emit)
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

    async def _stream_llm(
        self,
        model: str,
        messages: list[Message],
        tools: list[Any],
        emit: EventEmitter,
    ) -> Any:
        """Stream LLM output, emitting message.lifecycle events.

        Falls back to non-streaming chat() if the provider doesn't implement
        stream(). Returns a ChatResponse-like object with accumulated content
        and tool_calls.

        Emits in order:
        - message.started (with message_id)
        - message.delta (with message_id + delta) per chunk
        - message.completed (with message_id + content) on success
        - message.failed (with message_id + error) on failure
        """
        stream_fn = getattr(self.llm, "stream", None)
        if stream_fn is None:
            # Provider doesn't support streaming; use regular chat.
            return await self.llm.chat(model=model, messages=messages, tools=tools)

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        finish_reason: str | None = None

        # Emit message.started to signal the start of a new assistant message.
        await emit.message_started(message_id)

        try:
            async for chunk in stream_fn(
                model=model,
                messages=messages,
                tools=tools,
            ):
                if chunk.content:
                    content_parts.append(chunk.content)
                    # Emit each text chunk as message.delta with the same message_id.
                    await emit.message_delta(message_id, chunk.content)
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        except Exception as e:
            # Emit message.failed to signal the message was not completed.
            await emit.message_failed(message_id, str(e))
            raise

        final_content = "".join(content_parts) if content_parts else ""

        # Emit message.completed to signal the message is done streaming.
        await emit.message_completed(message_id, final_content)

        # Build a ChatResponse-like return so the main loop can handle uniformly.
        from paperforge.llm.base import ChatResponse
        return ChatResponse(
            content=final_content or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
