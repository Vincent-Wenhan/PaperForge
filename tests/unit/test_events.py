"""Tests for the events system."""

from __future__ import annotations

import pytest

from paperforge.orchestrator.events import (
    Event,
    EventEmitter,
    EventManager,
    EventPersistenceError,
    get_event_manager,
)


@pytest.mark.asyncio
async def test_event_manager_register_and_broadcast(storage):
    storage.create_run("run_a", title="a")
    mgr = EventManager(storage=storage)
    q = mgr.register("run_a")
    event = Event(type="test", data={"x": 1}, run_id="run_a")
    await mgr.broadcast(event)
    received = await q.get()
    assert received.type == "test"
    assert received.data == {"x": 1}


@pytest.mark.asyncio
async def test_event_emitter_text(storage):
    storage.create_run("run_t", title="t")
    mgr = EventManager(storage=storage)
    emitter = EventEmitter(run_id="run_t", manager=mgr)
    q = mgr.register("run_t")
    await emitter.text("Hello world")
    event = await q.get()
    assert event.type == "message.delta"
    assert event.data["text"] == "Hello world"


@pytest.mark.asyncio
async def test_event_emitter_tool_call(storage):
    from paperforge.llm.base import ToolCall
    storage.create_run("run_tc", title="tc")
    mgr = EventManager(storage=storage)
    emitter = EventEmitter(run_id="run_tc", manager=mgr)
    q = mgr.register("run_tc")
    await emitter.tool_call(ToolCall(id="c1", name="parse_paper", args={"pdf_path": "/x"}))
    event = await q.get()
    assert event.type == "tool.call"
    assert event.data["name"] == "parse_paper"


@pytest.mark.asyncio
async def test_unregister_removes_queue(storage):
    storage.create_run("run_x", title="x")
    mgr = EventManager(storage=storage)
    q = mgr.register("run_x")
    mgr.unregister("run_x", q)
    assert not mgr.has_subscribers("run_x")


def test_get_event_manager_singleton():
    mgr1 = get_event_manager()
    mgr2 = get_event_manager()
    assert mgr1 is mgr2


@pytest.mark.asyncio
async def test_persistence_failure_raises():
    class BrokenStore:
        def append_run_event(self, **kwargs):
            raise RuntimeError("disk full")

    mgr = EventManager(storage=BrokenStore())
    with pytest.raises(EventPersistenceError):
        await mgr.broadcast(Event(type="t", run_id="r"))
    # No event must leak to subscribers when persistence failed.
    assert not mgr.has_subscribers("r")
