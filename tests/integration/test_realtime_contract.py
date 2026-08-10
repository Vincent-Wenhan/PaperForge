"""Integration tests for the realtime / workspace contract (doc 23).

Covers user-visible streaming behavior: micro-batch coalescing, partial
stream recovery, workspace path safety, and follow-up without re-parse.
"""

from __future__ import annotations

import pytest

from pydantic import ValidationError

from paperforge.orchestrator.stream_writer import StreamWriter
from paperforge.orchestrator.workspace import (
    WorkspaceState,
    check_tool_prerequisites,
)
from paperforge.schemas.prd import Feature, PRD
from paperforge.schemas.workspace_policy import SafeWorkspacePolicy


class FakeEmit:
    def __init__(self) -> None:
        self.delta_count = 0
        self.deltas: list[str] = []

    async def message_delta(self, message_id: str, delta: str) -> None:
        self.delta_count += 1
        self.deltas.append(delta)

    async def message_completed(self, message_id: str, content: str) -> None:
        pass

    async def message_failed(self, message_id: str, error: str) -> None:
        pass


@pytest.mark.asyncio
async def test_stream_writer_coalesces_small_chunks(storage):
    """Many tiny chunks should not become one durable delta each (doc 23.1)."""
    storage.create_run(run_id="run_1", title="Realtime")
    storage.create_streaming_message("run_1", "msg_1")
    fake_emit = FakeEmit()
    writer = StreamWriter(
        run_id="run_1",
        message_id="msg_1",
        storage=storage,
        emit=fake_emit,
        flush_interval_s=100,
        checkpoint_interval_s=100,
        min_flush_chars=10,
    )

    for _ in range(25):
        await writer.push_text("a")

    content = await writer.finish()

    assert content == "a" * 25
    # 25 raw chunks must not become 25 durable deltas.
    assert fake_emit.delta_count < 25


@pytest.mark.asyncio
async def test_partial_stream_is_recoverable(storage):
    """A checkpointed stream is recoverable mid-stream (doc 23.2)."""
    storage.create_run(run_id="run_1", title="Realtime")
    storage.create_streaming_message("run_1", "msg_1")
    fake_emit = FakeEmit()
    writer = StreamWriter(
        run_id="run_1",
        message_id="msg_1",
        storage=storage,
        emit=fake_emit,
        checkpoint_interval_s=0,
    )

    await writer.push_text("hello")
    await writer.checkpoint()

    message = storage.list_messages("run_1")[0]
    assert message["content"] == "hello"
    assert message["status"] == "streaming"


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "/etc/passwd",
        "node_modules/x.js",
        ".git/config",
    ],
)
def test_workspace_policy_rejects_unsafe_paths(path):
    policy = SafeWorkspacePolicy()
    with pytest.raises(ValueError):
        policy.normalize(path)


def test_existing_workspace_can_be_patched_without_reparse():
    """Follow-up edits don't require re-parsing from the paper (doc 23.6)."""
    state = WorkspaceState(workspace_path="/tmp/app")
    allowed, missing = check_tool_prerequisites("apply_workspace_patch", state)
    assert allowed
    assert missing == []


def test_must_feature_requires_executable_acceptance():
    """A must-have feature needs at least one acceptance criterion (doc 23.4)."""
    with pytest.raises(ValidationError):
        PRD(
            prd_id="prd_1",
            product_name="Demo",
            features=[
                Feature(id="feature_upload", name="Upload", priority="must")
            ],
            acceptance_criteria=[],
        )
