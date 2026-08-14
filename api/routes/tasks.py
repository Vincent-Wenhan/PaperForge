"""Tasks API routes (doc 3.2).

A task represents a single productization workflow inside a run.
Multiple tasks can exist per run; each task has its own phase and status.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from paperforge.orchestrator.events import EventEmitter, get_event_manager
from paperforge.orchestrator.task_lifecycle import TaskLifecycleService
from paperforge.orchestrator.tasks import get_run_queue
from paperforge.storage.db import get_storage

router = APIRouter()


class TaskCreate(BaseModel):
    title: str | None = None
    goal: str | None = None
    phase: str = "init"
    status: str = "queued"


class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    phase: str | None = None
    goal: str | None = None


@router.post("")
async def create_task(run_id: str, req: TaskCreate) -> dict:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return storage.create_task(
        run_id=run_id,
        title=req.title,
        goal=req.goal,
        status=req.status,
        phase=req.phase,
    )


@router.get("")
async def list_tasks(run_id: str) -> list[dict]:
    storage = get_storage()
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return storage.list_tasks(run_id)


@router.get("/{task_id}")
async def get_task(run_id: str, task_id: str) -> dict:
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/steps")
async def get_task_steps(run_id: str, task_id: str) -> list[dict]:
    """Per-task step timeline, oldest first — survives reload."""
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task or task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return storage.list_steps_by_task(task_id)


@router.patch("/{task_id}")
async def update_task(run_id: str, task_id: str, req: TaskUpdate) -> dict:
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    emitter = EventEmitter(run_id=run_id, manager=get_event_manager(), task_id=task_id)
    lifecycle = TaskLifecycleService(storage, emitter)
    return await lifecycle.transition(
        task_id=task_id,
        status=req.status,
        phase=req.phase,
    )


@router.delete("/{task_id}")
async def delete_task(run_id: str, task_id: str) -> dict:
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    storage.delete_task(task_id)
    return {"task_id": task_id, "deleted": True}


@router.post("/{task_id}/cancel")
async def cancel_task(run_id: str, task_id: str) -> dict:
    """Cancel a single task, leaving the Run usable as a persistent thread."""
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in {"queued", "running", "waiting_user", "waiting_approval"}:
        raise HTTPException(status_code=409, detail="Task is not cancellable")

    queue = get_run_queue()
    if task["status"] == "running":
        await queue.cancel_and_wait(run_id)

    emitter = EventEmitter(run_id=run_id, manager=get_event_manager(), task_id=task_id)
    lifecycle = TaskLifecycleService(storage, emitter)
    await lifecycle.transition(task_id=task_id, status="cancelled")

    run = storage.get_run(run_id)
    previous = run.get("status") if run else "running"
    storage.update_run_status(run_id, "active")

    await emitter.run_status_changed("active", previous)
    await emitter.run_updated(status="active")

    return {"status": "cancelled", "task_id": task_id, "run_id": run_id}
