"""Default RQ worker entrypoint (API-mode jobs). The Playwright scraping
worker (M4) runs as a separate container with its own queue."""

from redis import Redis
from rq import Queue, Worker

from api.config import get_settings

QUEUES = ["default"]


def run() -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    worker = Worker([Queue(name, connection=connection) for name in QUEUES],
                    connection=connection)
    worker.work()


if __name__ == "__main__":
    run()
