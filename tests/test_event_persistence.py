from __future__ import annotations

import pytest

from paperforge.orchestrator.events import Event, EventManager


@pytest.mark.asyncio
async def test_event_manager_replays_durable_task_events(storage):
    storage.create_run("run_events", "Events", status="active")
    manager = EventManager(storage=storage)

    event = Event(
        type="task.phase.changed",
        data={"phase": "planned"},
        run_id="run_events",
        task_id="task_1",
    )
    await manager.broadcast(event)

    assert event.seq == 1
    assert storage.get_max_event_seq("run_events") == 1

    restarted = EventManager(storage=storage)
    history = restarted.get_history("run_events")
    assert len(history) == 1
    assert history[0].seq == 1
    assert history[0].task_id == "task_1"
    assert history[0].data == {"phase": "planned"}

