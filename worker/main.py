"""RQ worker entrypoint. WORKER_QUEUES picks the role: "default" is the API
worker (Mode A jobs), "scrape" is the Playwright container (Mode B jobs)."""

import os

from redis import Redis
from rq import Queue, Worker

from api.config import get_settings


def run() -> None:
    settings = get_settings()
    queues = [q.strip() for q in os.environ.get("WORKER_QUEUES", "default").split(",") if q.strip()]
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(name, connection=connection) for name in queues],
                    connection=connection)
    worker.work()


if __name__ == "__main__":
    run()
