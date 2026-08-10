"""Tests for PR 9 production runtime: worker leases and stale reclaim (doc 37)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from paperforge.storage.db import Storage


def _lease_until(seconds: int) -> str:
    return (datetime.utcnow() + timedelta(seconds=seconds)).isoformat()


def test_claim_next_task_marks_running_and_increments_attempt(storage: Storage):
    run = storage.create_run("run_l1", "Lease", status="active")
    task = storage.create_task(run_id=run["id"], title="t", status="queued")

    claimed = storage.claim_next_task("worker-1", _lease_until(300))
    assert claimed["id"] == task["id"]
    stored = storage.get_task(task["id"])
    assert stored["status"] == "running"
    assert stored["lease_owner"] == "worker-1"
    assert stored["attempt"] == 1

    # A second worker cannot claim the same running task.
    assert storage.claim_next_task("worker-2", _lease_until(300)) is None


def test_renew_task_lease_only_by_owner(storage: Storage):
    run = storage.create_run("run_l2", "Lease", status="active")
    task = storage.create_task(run_id=run["id"], title="t", status="queued")
    storage.claim_next_task("worker-1", _lease_until(300))

    assert storage.renew_task_lease(task["id"], "worker-1", _lease_until(600)) is True
    # Wrong owner cannot renew.
    assert storage.renew_task_lease(task["id"], "worker-2", _lease_until(600)) is False


def test_reconcile_stale_tasks_requeues_expired_lease(storage: Storage):
    run = storage.create_run("run_l3", "Lease", status="active")
    task = storage.create_task(run_id=run["id"], title="t", status="queued")
    # Claim with an already-expired lease.
    storage.claim_next_task("worker-1", _lease_until(-60))

    n = storage.reconcile_stale_tasks()
    assert n == 1
    stored = storage.get_task(task["id"])
    assert stored["status"] == "queued"
    assert stored["lease_owner"] is None

    # It is claimable again.
    reclaimed = storage.claim_next_task("worker-2", _lease_until(300))
    assert reclaimed["id"] == task["id"]
