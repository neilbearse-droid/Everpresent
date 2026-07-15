"""RQ worker entrypoint. WORKER_QUEUES picks the role: "default" is the API
worker (Mode A jobs), "scrape" is the Playwright container (Mode B jobs)."""

import os

import structlog
from redis import Redis
from rq import Queue, Worker
from sqlmodel import select

from api.config import get_settings

log = structlog.get_logger()


def reclaim_orphaned_runs() -> None:
    """A run left at 'running' when the worker restarted has no job to finish
    it — mark it failed so it doesn't sit stuck forever. Safe with a single
    worker (our deployment); each restart reclaims its own abandoned runs."""
    from sqlmodel import Session

    from api.db import get_engine
    from api.models import Run, RunStatus, utcnow

    try:
        with Session(get_engine()) as session:
            orphaned = session.exec(select(Run).where(Run.status == RunStatus.running)).all()
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
