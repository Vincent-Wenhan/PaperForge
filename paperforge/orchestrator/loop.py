"""Orchestrator main loop.

Implements the agentic loop: LLM → tool → LLM, until LLM stops calling tools.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message, ToolCall
from paperforge.llm.factory import get_llm_client
from paperforge.observability.metrics import get_metrics
from paperforge.orchestrator.approvals import (
    ApprovalPolicy,
    ToolSpec as ApprovalToolSpec,
    get_approval_registry,
)
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


def _approval_spec(name: str) -> ApprovalToolSpec:
    """Map a tool name to its risk for the approval policy.

    Mirrors the resource-gate `ToolSpec` risk in workspace.py. Sandbox exec
    tools are isolated-local by default, so they're trusted under
    TRUST_WORKSPACE; network/destructive reads are the ones that prompt.
    """
    risk_map = {
        "parse_paper": "read",
        "compose_capabilities": "read",
        "plan_product": "read",
        "inspect_workspace": "read",
        "read_workspace_file": "read",
        "run_checks": "sandbox_exec",
        "run_in_sandbox": "sandbox_exec",
        "restart_sandbox": "sandbox_exec",
        "generate_nextjs_app": "workspace_write",
        "apply_workspace_patch": "workspace_write",
        "build_and_repair": "workspace_write",
        "repair_app": "workspace_write",
    }
    return ApprovalToolSpec(name=name, risk=risk_map.get(name, "read"))


class RunPhase(str, Enum):
    """Tracked only for the UI's displayed step; not a tool-permission gate.

    `DONE` was removed as a thread terminal — a finished task leaves the Run
    active as a persistent thread; the only true terminal is ``archived_at``.
    """

    INIT = "init"
    PARSED = "parsed"
    COMPOSED = "composed"
    PLANNED = "planned"
    GENERATED = "generated"
    VERIFIED = "verified"
    PREVIEW_READY = "preview_ready"
    ERROR = "error"


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
        self.task_id = task_id
        emit = EventEmitter(run_id=run_id, manager=event_manager, task_id=self.task_id)

        # Cancel is a task-level terminal: the Run is a persistent thread and
        # stays usable. The only thread-level terminal is archive.
        prev_status = self.storage.get_run_status(run_id) or "active"
        run_row = self.storage.get_run(run_id) or {}
        if run_row.get("archived_at"):
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
                            task_id=self.task_id,
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
                            task_id=self.task_id,
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
                        # Task completion != Run completion: finishing a
                        # task leaves the Run active as a persistent thread.
                        terminal_status = (
                            "waiting_user"
                            if waiting_for_user
                            else "active"
                        )
                        task_terminal = (
                            "waiting_user"
                            if waiting_for_user
                            else "completed"
                        )
                        previous = self.storage.get_run_status(run_id) or "running"
                        self.storage.update_run_status(run_id, terminal_status)
                        self._update_task(
                            status=task_terminal,
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
                        task_id=self.task_id,
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
            # Current task stopped; persistent thread stays usable.
            self._update_task(status="cancelled", phase=self.phase.value)
            self.storage.update_run_status(run_id, "active")
            with contextlib.suppress(Exception):
                await emit.run_status_changed("active", previous)
                await emit.run_updated(status="active", phase=self.phase.value)
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
        # Resource gate is the sole tool-prerequisite authority.
        workspace_state = load_workspace_state(self.storage, run_id)
        allowed, missing = check_tool_prerequisites(call.name, workspace_state)
        if not allowed:
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

        # HITL: risk-based approval gate. Workspace reads and writes
        # are trusted under TRUST_WORKSPACE so a continuous agent can patch its
        # own workspace without a modal every turn; only network/destructive
        # tools prompt.
        policy = getattr(self, "_approval_policy", None) or ApprovalPolicy()
        if policy.requires(_approval_spec(call.name)):
            approval = self.storage.create_approval(
                run_id=run_id,
                tool_name=call.name,
                args=call.args,
                task_id=self.task_id,
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
        - message.delta (with message_id + delta) per text chunk
        - message.completed (with message_id + content) on success
        - message.failed (with message_id + error) on failure

        Consumes `ProviderStreamEvent` so the orchestrator never
        depends on a provider-specific delta shape. Falls back to `stream()`
        chunks or plain `chat()` if the provider lacks a native event stream.
        """
        stream_events = getattr(self.llm, "stream_events", None)
        if stream_events is None:
            return await self._stream_chunks_with_fallback(
                model=model, messages=messages, tools=tools,
                emit=emit, run_id=run_id,
            )

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        tool_calls: list[ToolCall] = []
        finish_reason: str | None = None

        # Persist the public ID before emitting the first lifecycle event so a
        # refresh can always reconcile the stream with one durable row.
        self.storage.create_streaming_message(
            run_id, message_id, task_id=self.task_id
        )
        await emit.message_started(message_id)

        writer = StreamWriter(
            run_id=run_id,
            message_id=message_id,
            storage=self.storage,
            emit=emit,
        )

        metrics = get_metrics()
        provider_started = time.monotonic()
        provider_first_delta: float | None = None

        try:
            async for ev in stream_events(model=model, messages=messages, tools=tools):
                if ev.kind == "text_delta":
                    if provider_first_delta is None:
                        provider_first_delta = time.monotonic()
                        metrics.record_duration(
                            "provider_ttft_ms",
                            provider_first_delta - provider_started,
                        )
                    await writer.push_text(ev.text or "")
                elif ev.kind == "tool_done":
                    tool_calls.append(
                        ToolCall(
                            id=ev.tool_call_id or "",
                            name=ev.tool_name or "",
                            args=ev.arguments or {},
                        )
                    )
                elif ev.kind == "done":
                    finish_reason = ev.finish_reason or finish_reason
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

    async def _stream_chunks_with_fallback(
        self,
        model: str,
        messages: list[Message],
        tools: list[Any],
        emit: EventEmitter,
        run_id: str,
    ) -> Any:
        """Legacy stream() chunk path used only when no ProviderStreamEvent
        stream exists. Accumulates provider chunks the same way it always did."""
        stream_fn = getattr(self.llm, "stream", None)
        if stream_fn is None:
            # Provider doesn't support streaming; use regular chat.
            return await self.llm.chat(model=model, messages=messages, tools=tools)

        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        tool_calls: list[ToolCall] = []
        finish_reason: str | None = None

        self.storage.create_streaming_message(
            run_id, message_id, task_id=self.task_id
        )
        await emit.message_started(message_id)

        writer = StreamWriter(
            run_id=run_id,
            message_id=message_id,
            storage=self.storage,
            emit=emit,
        )

        metrics = get_metrics()
        provider_started = time.monotonic()
        provider_first_delta: float | None = None

        try:
            async for chunk in stream_fn(
                model=model,
                messages=messages,
                tools=tools,
            ):
                if chunk.content:
                    if provider_first_delta is None:
                        provider_first_delta = time.monotonic()
                        metrics.record_duration(
                            "provider_ttft_ms",
                            provider_first_delta - provider_started,
                        )
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
