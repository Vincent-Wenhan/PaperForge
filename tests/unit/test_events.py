"""Tests for the events system."""

from __future__ import annotations

import pytest

from paperforge.orchestrator.events import Event, EventEmitter, EventManager, get_event_manager


@pytest.mark.asyncio
async def test_event_manager_register_and_broadcast():
    mgr = EventManager()
    q = mgr.register("run_a")
    event = Event(type="test", data={"x": 1}, run_id="run_a")
    await mgr.broadcast(event)
    received = await q.get()
    assert received.type == "test"
    assert received.data == {"x": 1}


@pytest.mark.asyncio
async def test_event_emitter_text():
    mgr = EventManager()
    emitter = EventEmitter(run_id="run_t", manager=mgr)
    q = mgr.register("run_t")
    await emitter.text("Hello world")
    event = await q.get()
    assert event.type == "message.delta"
    assert event.data["text"] == "Hello world"


@pytest.mark.asyncio
async def test_event_emitter_tool_call():
    from paperforge.llm.base import ToolCall
    mgr = EventManager()
    emitter = EventEmitter(run_id="run_tc", manager=mgr)
    q = mgr.register("run_tc")
    await emitter.tool_call(ToolCall(id="c1", name="parse_paper", args={"pdf_path": "/x"}))
    event = await q.get()
    assert event.type == "tool.call"
    assert event.data["name"] == "parse_paper"


@pytest.mark.asyncio
async def test_unregister_removes_queue():
    mgr = EventManager()
    q = mgr.register("run_x")
    mgr.unregister("run_x", q)
    assert not mgr._subscribers.get("run_x")


def test_get_event_manager_singleton():
    mgr1 = get_event_manager()
    mgr2 = get_event_manager()
    assert mgr1 is mgr2
