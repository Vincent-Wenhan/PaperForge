"""Tests for the Storage class."""

from __future__ import annotations

from paperforge.storage.db import Storage


def test_create_and_get_run(storage: Storage):
    run = storage.create_run("run_abc", "Test Run", status="active")
    assert run["id"] == "run_abc"
    assert run["title"] == "Test Run"

    fetched = storage.get_run("run_abc")
    assert fetched is not None
    assert fetched["title"] == "Test Run"


def test_list_runs_ordered(storage: Storage):
    storage.create_run("run_a", "A")
    storage.create_run("run_b", "B")
    runs = storage.list_runs()
    assert len(runs) >= 2


def test_add_and_list_messages(storage: Storage):
    storage.create_run("run_msg", "Msg Run")
    storage.add_message("run_msg", role="user", content="Hello")
    storage.add_message("run_msg", role="assistant", content="Hi there")
    msgs = storage.list_messages("run_msg")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["content"] == "Hi there"


def test_save_and_get_sandbox(storage: Storage):
    storage.create_run("run_sb", "Sandbox Run")
    storage.save_sandbox(
        sandbox_id="sb_test",
        run_id="run_sb",
        app_path="/tmp/app",
        container_id="container-123",
        preview_port=3001,
        status="running",
    )
    sb = storage.get_sandbox("sb_test")
    assert sb is not None
    assert sb["container_id"] == "container-123"
    assert sb["preview_port"] == 3001


def test_upsert_and_get_paper(storage: Storage):
    storage.upsert_paper(
        paper_id="paper_test",
        title="Test Paper",
        pdf_path="/tmp/test.pdf",
        status="uploaded",
    )
    paper = storage.get_paper("paper_test")
    assert paper is not None
    assert paper["title"] == "Test Paper"
    assert paper["status"] == "uploaded"


def test_save_and_get_artifact(storage: Storage):
    storage.create_run("run_art", "Artifact Run")
    artifact_id = storage.save_artifact(
        run_id="run_art",
        artifact_type="capability_card",
        data={"paper_id": "p", "title": "T"},
        metadata={"source": "test"},
    )
    loaded = storage.get_artifact(artifact_id)
    assert loaded is not None
    assert loaded["data"]["title"] == "T"
    assert loaded["metadata"]["source"] == "test"


def test_create_and_resolve_approval(storage: Storage):
    storage.create_run("run_apv", "Approval Run")
    approval = storage.create_approval("run_apv", "run_in_sandbox", {"app_path": "/x"})
    assert approval["status"] == "pending"
    storage.resolve_approval(approval["id"], approved=True)
    fetched = storage.get_approval(approval["id"])
    assert fetched["status"] == "approved"
