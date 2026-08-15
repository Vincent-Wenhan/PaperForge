"""Tests for PR 9 production runtime: worker leases and stale reclaim (doc 37)."""

from __future__ import annotations

from datetime import datetime, timedelta

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


def test_recover_stale_running_requeues_expired_lease(storage: Storage):
    run = storage.create_run("run_l3", "Lease", status="active")
    task = storage.create_task(run_id=run["id"], title="t", status="queued")
    # Claim with an already-expired lease.
    storage.claim_next_task("worker-1", _lease_until(-60))

    recovered = storage.recover_stale_running_tasks()
    assert len(recovered) == 1
    assert recovered[0]["id"] == task["id"]
    assert recovered[0]["status"] == "queued"
    stored = storage.get_task(task["id"])
    assert stored["status"] == "queued"
    assert stored["lease_owner"] is None

    # It is claimable again.
    reclaimed = storage.claim_next_task("worker-2", _lease_until(300))
    assert reclaimed["id"] == task["id"]


def test_claim_task_cannot_cross_claim_other_runs(storage: Storage):
    """Exact claim must never take a task belonging to another run (doc 7)."""
    run_a = storage.create_run("run_ca", "A", status="active")
    run_b = storage.create_run("run_cb", "B", status="active")
    a = storage.create_task(run_id=run_a["id"], title="a", status="queued")
    b = storage.create_task(run_id=run_b["id"], title="b", status="queued")

    # Exact-claim task A; B must remain untouched (no global oldest stealing).
    claimed = storage.claim_task(task_id=a["id"], worker_id="worker-1", lease_until=_lease_until(300))
    assert claimed["id"] == a["id"]
    assert storage.get_task(a["id"])["status"] == "running"
    assert storage.get_task(b["id"])["status"] == "queued"

    # Exact-claim is idempotent-guarded: cannot re-claim a running task.
    assert storage.claim_task(task_id=a["id"], worker_id="worker-2", lease_until=_lease_until(300)) is None


def test_list_queued_tasks_for_restart_recovery(storage: Storage):
    """Queued tasks are listable for startup re-enqueue (doc 8)."""
    run_a = storage.create_run("run_lq", "Queue", status="active")
    t1 = storage.create_task(run_id=run_a["id"], title="t1", status="queued", priority=50)
    t2 = storage.create_task(run_id=run_a["id"], title="t2", status="queued", priority=100)

    queued = storage.list_queued_tasks()
    assert {q["id"] for q in queued} == {t1["id"], t2["id"]}
    # Ordered by priority desc.
    assert queued[0]["id"] == t2["id"]
