"""RQ worker entrypoint. WORKER_QUEUES picks the role: "default" is the API
worker (Mode A jobs), "scrape" is the Playwright container (Mode B jobs)."""

import os
from datetime import UTC, datetime, timedelta

import structlog
from redis import Redis
from rq import Queue, Worker
from sqlmodel import select

from api.config import get_settings

log = structlog.get_logger()


def _as_utc(stamp: datetime) -> datetime:
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


# Longer than any job can legitimately take (Mode A 1h + Mode B 4h timeouts),
# so a run still "running" past this has no live job behind it.
ORPHAN_AFTER = 5 * 60 * 60  # seconds


def reclaim_orphaned_runs() -> None:
    """A run stuck at 'running' long past every job timeout has no job left
    to finish it — mark it failed so it doesn't sit stuck forever.

    Only STALE runs are reclaimed: a restart mid-run must not fail a run whose
    Mode B job is still queued in Redis (it resumes after the restart), and in
    a split deployment one worker's restart must not fail the other's run."""
    from sqlmodel import Session

    from api.db import get_engine
    from api.models import Run, RunStatus, utcnow

    try:
        with Session(get_engine()) as session:
            cutoff = utcnow() - timedelta(seconds=ORPHAN_AFTER)
            orphaned = [
                r
                for r in session.exec(select(Run).where(Run.status == RunStatus.running)).all()
                if _as_utc(r.started_at or r.created_at) < cutoff
            ]
            for run in orphaned:
                run.status = RunStatus.failed
                run.error = "worker restarted while this run was in progress"
                run.finished_at = utcnow()
                session.add(run)
            if orphaned:
                session.commit()
                log.info("worker.reclaimed_orphaned_runs", count=len(orphaned))
    except Exception:  # noqa: BLE001 — never block worker startup on cleanup
        log.exception("worker.reclaim_failed")


def run() -> None:
    settings = get_settings()
    reclaim_orphaned_runs()
    queues = [q.strip() for q in os.environ.get("WORKER_QUEUES", "default").split(",") if q.strip()]
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(name, connection=connection) for name in queues],
                    connection=connection)
    worker.work()


if __name__ == "__main__":
    run()
