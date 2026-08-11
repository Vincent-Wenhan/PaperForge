"""Task lifecycle state machine tests (doc 27)."""

from __future__ import annotations

import pytest

from paperforge.schemas.task_lifecycle import (
    ALLOWED_TRANSITIONS,
    TaskStatus,
    task_transform,
    validate_task_transition,
)


def test_allowed_transitions_match_doc():
    assert validate_task_transition(TaskStatus.QUEUED, TaskStatus.RUNNING)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.WAITING_USER)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.COMPLETED)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert validate_task_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED)
    assert validate_task_transition(TaskStatus.WAITING_USER, TaskStatus.QUEUED)
    assert validate_task_transition(TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING)


def test_illegal_transitions_rejected():
    # completed/failed/cancelled are terminal.
    assert not validate_task_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)
    assert not validate_task_transition(TaskStatus.FAILED, TaskStatus.QUEUED)
    assert not validate_task_transition(TaskStatus.QUEUED, TaskStatus.COMPLETED)
    assert not validate_task_transition(TaskStatus.RUNNING, TaskStatus.QUEUED)


def test_task_transform_refuses_invalid(storage):
    run = storage.create_run("run_tl", "TL", status="active")
    task = storage.create_task(run_id=run["id"], title="t", status="queued")
    # queued -> running is fine.
    assert task_transform(storage, task_id=task["id"], to=TaskStatus.RUNNING)
    assert storage.get_task(task["id"])["status"] == "running"
    # running -> queued is not allowed.
    assert not task_transform(storage, task_id=task["id"], to=TaskStatus.QUEUED)


def test_unknown_status_defaults_to_queued():
    assert TaskStatus("queued") == TaskStatus.QUEUED
