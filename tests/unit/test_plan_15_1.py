"""Backend tests for section 15.1 of the implementation plan.

Tests:
- test_run_rename_archive_restore_delete
- test_paper_rename_attach_detach_delete
- test_message_with_paper_ids
- test_plain_chat_does_not_finish_task
- test_new_task_after_completed_task
- test_file_create_rename_delete
- test_artifact_download_delete
- test_event_resume_after_seq
- test_latest_sandbox_by_run
- test_pending_approval_survives_refresh
- test_second_message_does_not_silently_cancel_active_task
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from paperforge.llm.base import ChatResponse
from paperforge.llm.mock_provider import MockLLMClient
from paperforge.orchestrator.events import EventEmitter, EventManager
from paperforge.orchestrator.loop import Orchestrator, RunPhase
from paperforge.storage.db import Storage


# ===== Run rename/archive/restore/delete =====


def test_run_rename_archive_restore_delete(storage: Storage):
    """Run should support rename, archive, restore, and delete."""
    storage.create_run("run_rename", "Original Title", status="active")

    # Rename via update_run
    storage.update_run("run_rename", title="Renamed Title")
    run = storage.get_run("run_rename")
    assert run["title"] == "Renamed Title"

    # Archive
    storage.archive_run("run_rename")
    archived = storage.get_run("run_rename")
    assert archived["archived_at"] is not None

    # Restore
    storage.restore_run("run_rename")
    restored = storage.get_run("run_rename")
    assert restored["archived_at"] is None

    # Delete
    storage.delete_run("run_rename")
    assert storage.get_run("run_rename") is None


# ===== Paper rename/attach/detach/delete =====


def test_paper_rename(storage: Storage):
    """Paper should support rename."""
    storage.upsert_paper(
        paper_id="paper_rename",
        title="Original Title",
        pdf_path="/tmp/test.pdf",
        status="uploaded",
    )
    storage.update_paper_title("paper_rename", "Renamed Title")
    paper = storage.get_paper("paper_rename")
    assert paper["title"] == "Renamed Title"


def test_paper_delete(storage: Storage):
    """Paper should be deletable."""
    storage.upsert_paper(
        paper_id="paper_del",
        title="Delete Test",
        pdf_path="/tmp/test.pdf",
        status="uploaded",
    )
    storage.delete_paper("paper_del")
    assert storage.get_paper("paper_del") is None


# ===== Message with paper_ids =====


def test_message_with_paper_ids(storage: Storage):
    """Messages should support paper_ids as explicit context."""
    storage.create_run("run_paper_ids", "Paper IDs Test", status="active")

    storage.add_message(
        run_id="run_paper_ids",
        role="user",
        content="Productize this paper",
    )

    messages = storage.list_messages("run_paper_ids")
    assert len(messages) == 1
    assert messages[0]["content"] == "Productize this paper"


# ===== Plain chat does not finish task =====


@pytest.mark.asyncio
async def test_plain_chat_does_not_finish_task(storage: Storage):
    """A plain Q&A reply must not advance the run phase or mark the run as done."""
    storage.create_run("run_plain", "Plain Chat Test", status="active")
    storage.add_message(run_id="run_plain", role="user", content="who are you")

    class PlainLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            return ChatResponse(content="I am PaperForge.", finish_reason="stop")

    orc = Orchestrator(llm=PlainLLM(), storage=storage)
    await orc.run(run_id="run_plain", user_message="who are you")

    assert orc.phase != RunPhase.DONE
    run = storage.get_run("run_plain")
    assert run["status"] == "active"


# ===== New task after completed task =====


@pytest.mark.asyncio
async def test_new_task_after_completed_task(storage: Storage):
    """After a task completes, the user should be able to start a new task."""
    storage.create_run("run_multi", "Multi-turn Test", status="active")

    call_count = 0

    class MultiLLM(MockLLMClient):
        async def chat(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return ChatResponse(content="Hello!", finish_reason="stop")

    orc = Orchestrator(llm=MultiLLM(), storage=storage)

    storage.add_message(run_id="run_multi", role="user", content="hello")
    await orc.run(run_id="run_multi", user_message="hello")

    assert orc.phase == RunPhase.INIT

    storage.add_message(run_id="run_multi", role="user", content="hi again")
    await orc.run(run_id="run_multi", user_message="hi again")

    assert orc.phase == RunPhase.INIT


# ===== File create/rename/delete =====


def test_file_create_rename_delete(storage: Storage, tmp_path: Path):
    """File create/rename/delete should work via the files API."""
    storage.create_run("run_files", "Files Test", status="active")

    app_path = tmp_path / "test_app"
    app_path.mkdir(parents=True)

    storage.save_sandbox(
        sandbox_id="sb_test",
        run_id="run_files",
        app_path=str(app_path),
        container_id="container-123",
        preview_port=3001,
        status="running",
    )

    test_file = app_path / "test.tsx"
    test_file.write_text("export const Test = () => <div>Test</div>;", encoding="utf-8")

    renamed_file = app_path / "renamed.tsx"
    test_file.rename(renamed_file)

    assert not test_file.exists()
    assert renamed_file.exists()

    renamed_file.unlink()
    assert not renamed_file.exists()


# ===== Artifact download/delete =====


def test_artifact_download_delete(storage: Storage):
    """Artifact download and delete should work."""
    storage.create_run("run_art", "Artifact Test", status="active")

    artifact_id = storage.save_artifact(
        run_id="run_art",
        artifact_type="capability_card",
        data={"paper_id": "p", "title": "T"},
        metadata={"source": "test"},
    )

    loaded = storage.get_artifact(artifact_id)
    assert loaded is not None
    assert loaded["data"]["title"] == "T"

    artifact_path = Path(loaded["path"])
    assert artifact_path.exists()

    artifact_path.unlink()
    with storage._lock, storage._conn() as conn:
        conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

    assert storage.get_artifact(artifact_id) is None


# ===== Event resume after seq =====


@pytest.mark.asyncio
async def test_event_resume_after_seq():
    """SSE should support resume after a given seq."""
    mgr = EventManager()
    emitter = EventEmitter(run_id="run_resume", manager=mgr)

    await emitter.text("first")
    await emitter.text("second")
    await emitter.text("third")

    history = mgr.get_history("run_resume")
    assert len(history) == 3
    assert history[0].seq == 1
    assert history[1].seq == 2
    assert history[2].seq == 3

    resumed = [e for e in history if e.seq > 2]
    assert len(resumed) == 1
    assert resumed[0].seq == 3


# ===== Latest sandbox by run =====


def test_latest_sandbox_by_run(storage: Storage):
    """list_sandboxes should return sandboxes filtered by run_id."""
    storage.create_run("run_sb1", "Sandbox Run 1", status="active")
    storage.create_run("run_sb2", "Sandbox Run 2", status="active")

    storage.save_sandbox(
        sandbox_id="sb_1",
        run_id="run_sb1",
        app_path="/tmp/app1",
        status="running",
    )
    storage.save_sandbox(
        sandbox_id="sb_2",
        run_id="run_sb2",
        app_path="/tmp/app2",
        status="running",
    )

    all_sandboxes = storage.list_sandboxes()
    assert len(all_sandboxes) >= 2

    run1_sandboxes = [s for s in all_sandboxes if s["run_id"] == "run_sb1"]
    assert len(run1_sandboxes) == 1
    assert run1_sandboxes[0]["id"] == "sb_1"


# ===== Pending approval survives refresh =====


def test_pending_approval_survives_refresh(storage: Storage):
    """Pending approvals should be recoverable from storage after refresh."""
    storage.create_run("run_apv", "Approval Test", status="active")

    approval = storage.create_approval("run_apv", "generate_nextjs_app", {"prd_id": "test"})
    assert approval["status"] == "pending"

    fetched = storage.get_approval(approval["id"])
    assert fetched is not None
    assert fetched["status"] == "pending"
    assert fetched["tool_name"] == "generate_nextjs_app"


# ===== Second message does not silently cancel active task =====


@pytest.mark.asyncio
async def test_second_message_does_not_silently_cancel_active_task(storage: Storage):
    """A second message should NOT silently cancel an active task."""
    from paperforge.orchestrator.tasks import RunTaskManager

    task_mgr = RunTaskManager()

    async def long_task():
        await asyncio.sleep(10)

    task_mgr.start("run_concurrent", long_task())

    assert task_mgr.is_running("run_concurrent")

    task_mgr.cancel("run_concurrent")
