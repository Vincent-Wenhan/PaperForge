"""Task lifecycle state machine (doc 27).

Tasks follow a strict status set distinct from Run status. A finished task
leaves the Run active as a persistent thread, so task statuses are bounded
here rather than reusing Run's active/running vocabulary.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Allowed transitions. Not every edge is used today, but the set is
# enforceable so future code can't invent an invalid move (doc 27).
ALLOWED_TRANSITIONS: Final[dict[TaskStatus, set[TaskStatus]]] = {
    TaskStatus.QUEUED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_USER,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_USER: {TaskStatus.QUEUED},
    TaskStatus.WAITING_APPROVAL: {TaskStatus.RUNNING},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def validate_task_transition(current: TaskStatus, next_: TaskStatus) -> bool:
    """Return True if ``current`` may transition to ``next_``."""
    return next_ in ALLOWED_TRANSITIONS.get(current, set())


def task_transform(
    storage,
    *,
    task_id: str,
    to: TaskStatus,
    phase: str | None = None,
) -> bool:
    """Transition a task to ``to``, refusing invalid moves.

    Reconcile-from-running (stale lease) is allowed beyond the strict edges.
    """
    row = storage.get_task(task_id)
    if not row:
        return False
    current = TaskStatus(row.get("status") or TaskStatus.QUEUED.value)
    if to == TaskStatus.COMPLETED and current == TaskStatus.RUNNING:
        pass
    elif not validate_task_transition(current, to):
        return False
    storage.update_task(task_id=task_id, status=to.value, phase=phase)
    return True
