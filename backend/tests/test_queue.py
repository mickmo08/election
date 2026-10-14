from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app import queue
from app.models import Job


def test_idempotent_enqueue(wdb):
    a = queue.enqueue(wdb, "noop", {}, idempotency_key="k-1")
    b = queue.enqueue(wdb, "noop", {}, idempotency_key="k-1")
    wdb.commit()
    assert a == b


def test_retry_then_dead_letter_then_requeue(wdb):
    calls = {"n": 0}

    @queue.handler("flaky-test")
    def flaky(db, payload):
        calls["n"] += 1
        raise RuntimeError("upstream timeout")

    jid = queue.enqueue(wdb, "flaky-test", {}, queue="q-test", max_attempts=2)
    wdb.commit()
    assert queue.run_one(wdb, "q-test")
    job = wdb.get(Job, jid)
    wdb.refresh(job)
    assert job.status == "failed" and job.attempts == 1 and job.run_at > datetime.now(UTC)
    wdb.execute(update(Job).where(Job.id == jid).values(run_at=datetime.now(UTC) - timedelta(seconds=1)))
    wdb.commit()
    assert queue.run_one(wdb, "q-test")
    wdb.refresh(job)
    assert job.status == "dead" and "upstream timeout" in job.last_error and calls["n"] == 2
    assert not queue.run_one(wdb, "q-test")  # dead jobs are not picked up
    assert queue.requeue_dead(wdb, jid)
    wdb.commit()

    @queue.handler("flaky-test")
    def fixed(db, payload):
        return {"ok": True}

    assert queue.run_one(wdb, "q-test")
    wdb.refresh(job)
    assert job.status == "succeeded" and job.result == {"ok": True}


def test_stale_running_job_is_recovered(wdb):
    @queue.handler("lease-test")
    def ok(db, payload):
        return {"done": True}

    jid = queue.enqueue(wdb, "lease-test", {}, queue="q-lease")
    wdb.execute(
        update(Job)
        .where(Job.id == jid)
        .values(status="running", locked_by="dead-worker", heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
    )
    wdb.commit()
    assert queue.run_one(wdb, "q-lease")
    job = wdb.get(Job, jid)
    wdb.refresh(job)
    assert job.status == "succeeded" and job.locked_by != "dead-worker"


def test_unknown_job_kind_dead_letters(wdb):
    jid = queue.enqueue(wdb, "does-not-exist", {}, queue="q-unknown", max_attempts=1)
    wdb.commit()
    queue.run_one(wdb, "q-unknown")
    job = wdb.get(Job, jid)
    wdb.refresh(job)
    assert job.status == "dead" and "no handler" in job.last_error
