"""Tasks API routes (doc 3.2).

A task represents a single productization workflow inside a run.
Multiple tasks can exist per run; each task has its own phase and status.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


@router.patch("/{task_id}")
async def update_task(run_id: str, task_id: str, req: TaskUpdate) -> dict:
    storage = get_storage()
    task = storage.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return storage.update_task(
        task_id=task_id,
        title=req.title,
        status=req.status,
        phase=req.phase,
        goal=req.goal,
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
