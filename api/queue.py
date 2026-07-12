from redis import Redis
from rq import Queue

from api.config import get_settings


def get_queue() -> Queue:
    return Queue("default", connection=Redis.from_url(get_settings().redis_url))


def enqueue_run(run_id: int) -> None:
    # Dotted path keeps api -> worker import coupling out of request handling;
    # the worker container resolves it.
    get_queue().enqueue("worker.jobs.run_mode_a", run_id, job_timeout=60 * 60)
