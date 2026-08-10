"""Orchestrator main loop.

Implements the agentic loop: LLM → tool → LLM, until LLM stops calling tools.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from paperforge.orchestrator.stream_writer import StreamWriter
from paperforge.orchestrator.tools import TOOL_DEFINITIONS, ToolContext, dispatch_tool
from paperforge.orchestrator.workspace import (
    available_resources,
    check_tool_prerequisites,
    load_workspace_state,
)
from paperforge.prompts import load_prompt
from paperforge.schemas.tool_result import ToolResult, ToolStatus
from paperforge.storage.db import Storage, get_storage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 1.0  # seconds
APPROVAL_TIMEOUT = 300  # 5 minutes

# Tools that require explicit user approval before execution (HITL).
DANGEROUS_TOOLS = {
    "generate_nextjs_app",
    "apply_workspace_patch",
    "run_in_sandbox",
    "restart_sandbox",
    "build_and_repair",
    "repair_app",
}


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
    RunPhase.GENERATED: {
        "verify_app",
        "build_and_repair",
        "repair_app",
        "inspect_workspace",
        "read_workspace_file",
        "apply_workspace_patch",
        "run_checks",
        "finish",
    },
    RunPhase.VERIFIED: {
        "verify_app",
        "build_and_repair",
        "repair_app",
        "inspect_workspace",
        "read_workspace_file",
        "apply_workspace_patch",
        "run_checks",
        "run_in_sandbox",
        "restart_sandbox",
        "stop_sandbox",
        "finish",
    },
    RunPhase.PREVIEW_READY: {
        "parse_paper",
        "compose_capabilities",
        "plan_product",
        "generate_nextjs_app",
        "verify_app",
        "build_and_repair",
        "repair_app",
        "inspect_workspace",
        "read_workspace_file",
        "apply_workspace_patch",
        "run_checks",
        "run_in_sandbox",
        "restart_sandbox",
        "stop_sandbox",
        "finish",
    },
    RunPhase.DONE: set(),
    RunPhase.ERROR: set(),
}

# Legacy mapping tool name → next phase. Kept for backwards compatibility
# with older tests that import it. The orchestrator loop now reads
# `next_phase` from the ToolResult returned by each tool handler.
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
        sandbox_manager: Any | None = None,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.storage = storage or get_storage()
        self.sandbox_manager = sandbox_manager
        self.phase: RunPhase = RunPhase.INIT
        self.task_id: str | None = None

    def _update_task(self, *, status: str | None = None, phase: str | None = None) -> None:
        if self.task_id:
            self.storage.update_task(
                task_id=self.task_id,
                status=status,
                phase=phase,
            )

    async def run(
        self,
        run_id: str,
        user_message: str,
        task_id: str | None = None,
    ) -> None:
        """Run the orchestrator loop for a single user message."""
        cfg = get_config()
        event_manager = get_event_manager()
        emit = EventEmitter(run_id=run_id, manager=event_manager)

        # Track previous status/phase so we only emit when they actually change.
        prev_status = self.storage.get_run_status(run_id) or "active"

        # Cancelled and completed runs are terminal checkpoints. A later
        # worker invocation must not silently resume their LLM workflow.
        if prev_status in {"cancelled", "done"}:
            return

        # Persist run status as running
        self.storage.update_run_status(run_id, "running")
        if prev_status != "running":
            await emit.run_status_changed("running", prev_status)

        # Restore phase from storage (default to INIT if missing)
        stored_phase = self.storage.get_run_phase(run_id) or "init"
        try:
            self.phase = RunPhase(stored_phase)
        except ValueError:
            self.phase = RunPhase.INIT

        self.task_id = task_id
        if self.task_id is None:
            task = self.storage.create_task(
                run_id=run_id,
                title=user_message.strip()[:120] or "Productization task",
                goal=user_message,
                status="running",
                phase=self.phase.value,
            )
            self.task_id = task["id"]
        else:
            self._update_task(status="running", phase=self.phase.value)

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
            sandbox_manager=self.sandbox_manager,
            task_id=self.task_id,
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
                    run_id=run_id,
                )
                if response is None:
                    # LLM failed; mark run as error so it doesn't stay "running".
                    self.phase = RunPhase.ERROR
                    self.storage.update_run_phase(run_id, self.phase.value)
                    self.storage.update_run_status(run_id, "error")
                    self._update_task(status="failed", phase=self.phase.value)
                    return  # error already emitted

                if response.tool_calls:
                    # Save assistant message with tool_calls
                    tool_calls_data = [
                        {"id": tc.id, "name": tc.name, "args": tc.args}
                        for tc in response.tool_calls
                    ]
                    if response.message_id:
                        self.storage.complete_message(
                            response.message_id,
                            response.content or "",
                            tool_calls_data,
                        )
                    else:
                        self.storage.add_message(
                            run_id=run_id,
                            role="assistant",
                            content=response.content or "",
                            tool_calls=tool_calls_data,
                        )
                    messages.append(
                        Message(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )

                    stop_loop = False
                    stopped_result: ToolResult | None = None
                    # Execute each tool call
                    for call in response.tool_calls:
                        await emit.tool_call(call)

                        result_str = await self._execute_tool_call(call, ctx, emit, run_id)

                        # Save tool result message
                        self.storage.add_message(
                            run_id=run_id,
                            role="tool",
                            content=result_str,
                            tool_call_id=call.id,
                            name=call.name,
                        )
                        messages.append(
                            Message(
                                role="tool",
                                content=result_str,
                                tool_call_id=call.id,
                            )
                        )

                        await emit.tool_result(call.name, result_str, call.id)

                        # Apply ToolResult side-effects (phase transition, stop)
                        try:
                            parsed = json.loads(result_str)
                        except (json.JSONDecodeError, TypeError):
                            parsed = {}

                        tool_result = ToolResult.model_validate(parsed) if isinstance(parsed, dict) else None
                        if tool_result is None:
                            continue

                        if tool_result.next_phase:
                            try:
                                new_phase = RunPhase(tool_result.next_phase)
                            except ValueError:
                                new_phase = self.phase
                            old_phase = self.phase
                            self.phase = new_phase
                            self.storage.update_run_phase(run_id, self.phase.value)
                            self._update_task(phase=self.phase.value)
                            await emit.task_phase_changed(
                                phase=self.phase.value,
                                previous_phase=old_phase.value,
                                task_id=self.task_id,
                            )
                            await emit.run_updated(phase=self.phase.value)

                        if tool_result.stop_loop:
                            stop_loop = True
                            stopped_result = tool_result
                            break

                    if stop_loop:
                        waiting_for_user = (
                            stopped_result is not None
                            and stopped_result.code == "needs_user_input"
                        )
                        terminal_status = (
                            "done"
                            if self.phase == RunPhase.DONE
                            else "waiting_user"
                            if waiting_for_user
                            else "active"
                        )
                        previous = self.storage.get_run_status(run_id) or "running"
                        self.storage.update_run_status(run_id, terminal_status)
                        self._update_task(
                            status="completed"
                            if terminal_status == "done"
                            else "waiting_user"
                            if waiting_for_user
                            else "active",
                            phase=self.phase.value,
                        )
                        if previous != terminal_status:
                            await emit.run_status_changed(terminal_status, previous)
                        await emit.run_updated(status=terminal_status, phase=self.phase.value)
                        await emit.run_finished()
                        return

                    # Loop back to LLM
                    continue

                # LLM returned text (no tool calls): message lifecycle is
                # handled inside _stream_llm (message.started → message.delta
                # → message.completed). Here we persist the final message and
                # keep the run active so the user can continue the conversation.
                final_content = response.content or ""
                if not response.message_id:
                    self.storage.add_message(
                        run_id=run_id,
                        role="assistant",
                        content=final_content,
                    )
                self.storage.update_run_status(run_id, "active")
                self._update_task(status="completed", phase=self.phase.value)
                await emit.run_updated(status="active", phase=self.phase.value)
                await emit.run_finished()
                return

            # Max iterations reached
            logger.warning(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
            await emit.run_error(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
            self.phase = RunPhase.ERROR
            self.storage.update_run_phase(run_id, self.phase.value)
            self.storage.update_run_status(run_id, "error")
            self._update_task(status="failed", phase=self.phase.value)
            await emit.run_updated(status="error", phase=self.phase.value)

        except asyncio.CancelledError:
            previous = self.storage.get_run_status(run_id) or "running"
            self.storage.update_run_status(run_id, "cancelled")
            self._update_task(status="cancelled", phase=self.phase.value)
            with contextlib.suppress(Exception):
                await emit.run_status_changed("cancelled", previous)
                await emit.run_updated(status="cancelled", phase=self.phase.value)
            raise
        except Exception as e:
            logger.exception(f"Orchestrator error: {e}")
            await emit.run_error(str(e))
            self.phase = RunPhase.ERROR
            self.storage.update_run_phase(run_id, self.phase.value)
            self.storage.update_run_status(run_id, "error")
            self._update_task(status="failed", phase=self.phase.value)
            await emit.run_updated(status="error", phase=self.phase.value)

    async def _execute_tool_call(
        self,
        call: ToolCall,
        ctx: ToolContext,
        emit: EventEmitter,
        run_id: str,
    ) -> str:
        """Execute a single tool call, applying resource gate and HITL approval."""
        # Resource gate: reject tools whose prerequisites aren't present, so
        # permission reflects real resources (doc 11) not an arbitrary phase.
        workspace_state = load_workspace_state(self.storage, run_id)
        allowed, missing = check_tool_prerequisites(call.name, workspace_state)
        if call.name in ALLOWED_TOOLS.get(self.phase, set()) and not allowed:
            return ToolResult(
                tool=call.name,
                status=ToolStatus.BLOCKED,
                error=f"Missing required resources: {', '.join(missing)}",
                code="resource_prerequisite",
                data={
                    "missing": missing,
                    "available": sorted(available_resources(workspace_state)),
                },
                retryable=True,
            ).model_dump_json()

        if call.name not in ALLOWED_TOOLS.get(self.phase, set()):
            return ToolResult(
                tool=call.name,
                status=ToolStatus.BLOCKED,
                error=f"Tool '{call.name}' is not allowed in phase '{self.phase.value}'.",
                code="phase_prerequisite",
                data={
                    "allowed_tools": sorted(ALLOWED_TOOLS.get(self.phase, set())),
                    "current_phase": self.phase.value,
                },
                retryable=True,
            ).model_dump_json()

        # HITL: dangerous tools require user approval
        if call.name in DANGEROUS_TOOLS:
            approval = self.storage.create_approval(
                run_id=run_id,
                tool_name=call.name,
                args=call.args,
            )
            approval_id = approval["id"]

            registry = get_approval_registry()
            registry.register(approval_id)

            await emit.approval_requested(
                approval_id=approval_id,
                tool_name=call.name,
                args=call.args,
            )

            approved = await registry.wait_for_resolution(
                approval_id,
                self.storage,
                timeout=APPROVAL_TIMEOUT,
            )
            if approved is None:
                self.storage.expire_approval(approval_id)
                registry.cleanup(approval_id)
                return ToolResult(
                    tool=call.name,
                    status=ToolStatus.BLOCKED,
                    error=f"Approval timed out after {APPROVAL_TIMEOUT}s.",
                    code="approval_timeout",
                    retryable=True,
                ).model_dump_json()

            registry.cleanup(approval_id)

            await emit.approval_resolved(
                approval_id=approval_id,
                approved=approved,
                tool_name=call.name,
            )

            if not approved:
                return ToolResult(
                    tool=call.name,
                    status=ToolStatus.BLOCKED,
                    error=f"Tool {call.name} was rejected by the user.",
                    code="approval_rejected",
                    retryable=False,
                ).model_dump_json()

        # Dispatch tool
        return await dispatch_tool(call.name, call.args, ctx)

    async def _call_llm_with_retry(
        self,
        model: str,
        messages: list[Message],
        tools: list[Any],
        emit: EventEmitter,
        run_id: str,
    ) -> Any:
        """Call LLM with exponential backoff retry. Returns None if all retries failed."""
        last_error: Exception | None = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                return await self._stream_llm(model, messages, tools, emit, run_id)
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
        run_id: str,
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
        tool_calls: list[ToolCall] = []
        finish_reason: str | None = None

        # Persist the public ID before emitting the first lifecycle event so a
        # refresh can always reconcile the stream with one durable row.
        self.storage.create_streaming_message(run_id, message_id)
        await emit.message_started(message_id)

        writer = StreamWriter(
            run_id=run_id,
            message_id=message_id,
            storage=self.storage,
            emit=emit,
        )

        try:
            async for chunk in stream_fn(
                model=model,
                messages=messages,
                tools=tools,
            ):
                if chunk.content:
                    # Coalesce deltas into ~40ms/batched events; durable
                    # content checkpoints at a slower 250ms cadence.
                    await writer.push_text(chunk.content)
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        except asyncio.CancelledError:
            self.storage.fail_message(message_id, "Message stream cancelled")
            with contextlib.suppress(Exception):
                await emit.message_failed(message_id, "Message stream cancelled")
            raise
        except Exception as e:
            # Emit message.failed to signal the message was not completed.
            self.storage.fail_message(message_id, str(e))
            await emit.message_failed(message_id, str(e))
            raise

        # flush remaining buffer, complete the durable message, emit completed.
        final_content = await writer.finish(tool_calls)

        # Build a ChatResponse-like return so the main loop can handle uniformly.
        from paperforge.llm.base import ChatResponse
        return ChatResponse(
            content=final_content or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            message_id=message_id,
        )
