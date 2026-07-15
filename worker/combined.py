"""Single-service worker entrypoint for managed hosts (Render): runs the
scheduler loop in a background thread and the RQ worker (draining both the
`default` and `scrape` queues) in the foreground. On a bigger deployment
these split back into separate services — see infra/docker-compose.yml — but
one process keeps a small hosting bill small.

Uses the Playwright image so the same process can run Mode B scrapes.
Set WORKER_QUEUES=default,scrape in the environment."""

import os
import threading

import structlog

from worker.main import run as run_worker
from worker.scheduler import run as run_scheduler

log = structlog.get_logger()


def main() -> None:
    os.environ.setdefault("WORKER_QUEUES", "default,scrape")
    # The scheduler is a resilient self-looping tick; run it alongside the
    # worker. The worker owns the main thread so its signal handlers work.
    scheduler_thread = threading.Thread(target=run_scheduler, name="scheduler", daemon=True)
    scheduler_thread.start()
    log.info("combined_worker.start", queues=os.environ["WORKER_QUEUES"])
    run_worker()


if __name__ == "__main__":
    main()
