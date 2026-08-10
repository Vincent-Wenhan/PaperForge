"""Self-check: ProgressReporter emits step.* events, persisted to steps table."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from paperforge.orchestrator.events import EventEmitter, EventManager
from paperforge.orchestrator.progress import ProgressReporter
from paperforge.storage.db import Storage


async def _scenario(storage: Storage) -> None:
    run_id = "run_prog"
    storage.create_run(run_id=run_id, title="Prog")
    mgr = EventManager(storage=storage)
    q = mgr.register(run_id)
    emit = EventEmitter(run_id=run_id, manager=mgr)

    task = storage.create_task(
        run_id=run_id,
        title="t",
        goal="g",
        status="running",
    )

    progress = ProgressReporter(run_id=run_id, task_id=task["id"], storage=storage, emit=emit)
    step_id = await progress.start(kind="codegen", title="Generating")
    await progress.progress(step_id, percent=50, detail="writing files")
    await progress.complete(step_id, summary="done")

    types: set[str] = set()
    while not q.empty():
        types.add(q.get_nowait().type)
    assert {"step.started", "step.progress", "step.completed"} <= types, types

    rows = storage.list_steps(run_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["summary"] == "done"
    print("progress-reporter ok")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="paperforge_progress_"))
    storage = Storage(db_path=tmp / "db.sqlite3", data_dir=tmp / "data")
    asyncio.run(_scenario(storage))


if __name__ == "__main__":
    main()
