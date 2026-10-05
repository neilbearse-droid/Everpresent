from redis import Redis
from rq import Queue

from api.config import get_settings


def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=Redis.from_url(get_settings().redis_url))


# Dotted paths keep api -> worker import coupling out of request handling;
# the worker containers resolve them. Mode A jobs run on the API worker
# ("default"); Mode B scraping runs on the Playwright container ("scrape").


def enqueue_run(run_id: int) -> None:
    # 3h: a large plan's matrix (~1,700 calls at concurrency 4) outlasts 1h,
    # and Mode A only writes results at the end, so a timeout loses the run.
    get_queue().enqueue("worker.jobs.run_mode_a", run_id, job_timeout=3 * 60 * 60)


def enqueue_run_mode_b(run_id: int) -> None:
    get_queue("scrape").enqueue("worker.jobs.run_mode_b", run_id, job_timeout=4 * 60 * 60)


def enqueue_page_crawl(tenant_id: int) -> None:
    get_queue().enqueue("worker.page_crawl.crawl_power_pages", tenant_id, job_timeout=15 * 60)


def enqueue_fanout_reprobe(run_id: int) -> None:
    get_queue().enqueue("worker.jobs.run_fanout_reprobe", run_id, job_timeout=30 * 60)


def enqueue_engine_check(tenant_id: int) -> None:
    # On the scrape queue: browser captures need the Playwright container.
    get_queue("scrape").enqueue("worker.smoke.run_engine_smoke", tenant_id, job_timeout=20 * 60)


def enqueue_demo_client(clerk_org_id: str | None) -> None:
    get_queue().enqueue("api.demo_client.build_demo_client_job", clerk_org_id,
                        job_timeout=20 * 60)


def enqueue_reprocess(tenant_id: int) -> None:
    get_queue().enqueue("api.processing_service.reprocess_tenant_job", tenant_id,
                        job_timeout=60 * 60)
