"""RQ worker entrypoint. WORKER_QUEUES picks the role: "default" is the API
worker (Mode A jobs), "scrape" is the Playwright container (Mode B jobs)."""

import os

import structlog
from redis import Redis
from rq import Queue, Worker

from api.config import get_settings

log = structlog.get_logger()


def reclaim_orphaned_runs() -> None:
    """Fail pending/running runs whose RQ job is gone (killed by a deploy or a
    crash), or that are past the hard in-flight ceiling. A run whose job is
    still queued or executing (e.g. on another worker) is left alone."""
    from sqlmodel import Session

    from api.db import get_engine
    from api.runs_service import reap_abandoned_runs

    try:
        with Session(get_engine()) as session:
            count = reap_abandoned_runs(session)
            if count:
                log.info("worker.reclaimed_orphaned_runs", count=count)
    except Exception:  # noqa: BLE001 — never block worker startup on cleanup
        log.exception("worker.reclaim_failed")


def wait_for_schema(timeout_s: float = 900.0, poll_s: float = 10.0) -> None:
    """Block until the database is migrated to this code's Alembic head.

    Render deploys the API (which migrates in preDeploy) and the worker
    independently; a worker that starts first would run new models against the
    old schema and fail every job and scheduler tick. A database with no
    alembic_version table (local create_all dev) is not waited on. After
    `timeout_s` it proceeds anyway, loudly, rather than never working."""
    import time
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from api.db import get_engine

    if os.environ.get("SKIP_SCHEMA_WAIT"):
        return
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with get_engine().connect() as conn:
                current = MigrationContext.configure(conn).get_current_revision()
        except Exception:  # noqa: BLE001 — DB not reachable yet: keep waiting
            current = "unreachable"
        if current is None or current == head:
            return
        if time.monotonic() > deadline:
            log.error("worker.schema_wait_timeout", current=current, head=head)
            return
        log.warning("worker.waiting_for_migrations", current=current, head=head)
        time.sleep(poll_s)


def run() -> None:
    settings = get_settings()
    wait_for_schema()
    reclaim_orphaned_runs()
    queues = [q.strip() for q in os.environ.get("WORKER_QUEUES", "default").split(",") if q.strip()]
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(name, connection=connection) for name in queues],
                    connection=connection)
    worker.work()


if __name__ == "__main__":
    run()
