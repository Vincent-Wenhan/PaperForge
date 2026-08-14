"""Task lifecycle state machine.

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


# Allowed transitions; empty sets are terminal.
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
