from redis import Redis
from rq import Queue

from api.config import get_settings


def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=Redis.from_url(get_settings().redis_url))


# Dotted paths keep api -> worker import coupling out of request handling;
# the worker containers resolve them. Mode A jobs run on the API worker
# ("default"); Mode B scraping runs on the Playwright container ("scrape").


def enqueue_run(run_id: int) -> None:
    get_queue().enqueue("worker.jobs.run_mode_a", run_id, job_timeout=60 * 60)


def enqueue_run_mode_b(run_id: int) -> None:
    get_queue("scrape").enqueue("worker.jobs.run_mode_b", run_id, job_timeout=4 * 60 * 60)


def enqueue_page_crawl(tenant_id: int) -> None:
    get_queue().enqueue("worker.page_crawl.crawl_power_pages", tenant_id, job_timeout=15 * 60)
