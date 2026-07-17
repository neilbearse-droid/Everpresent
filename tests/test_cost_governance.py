"""Full cost governance (§9): the monthly spend cap governs Mode B scraping
and SerpApi spend, not just Mode A token spend."""

from sqlmodel import select

from api.models import Result, ResultStatus, RunStatus, SurfaceCode, TenantSurface
from engine.costs import estimate_mode_b_cost_usd
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401
from tests.test_runs_mode_b import add_web_surface


def test_mode_b_cost_estimator():
    # Google AIO via SerpApi is a per-search API charge.
    assert estimate_mode_b_cost_usd(
        "google_aio", aio_provider="serpapi",
        serpapi_cost_per_search=0.0075, scrape_cost_per_page=0.02,
    ) == 0.0075
    # Direct AIO scrape and consumer-web scrapes are the per-page estimate.
    assert estimate_mode_b_cost_usd(
        "google_aio", aio_provider="direct",
        serpapi_cost_per_search=0.0075, scrape_cost_per_page=0.02,
    ) == 0.02
    assert estimate_mode_b_cost_usd(
        "chatgpt_web", aio_provider="serpapi",
        serpapi_cost_per_search=0.0075, scrape_cost_per_page=0.02,
    ) == 0.02


def _b_only(db_session, tenant):
    api_surface = db_session.exec(
        select(TenantSurface).where(
            TenantSurface.tenant_id == tenant.id,
            TenantSurface.code == SurfaceCode.openai_api,
        )
    ).one()
    api_surface.enabled = False
    db_session.add(api_surface)
    db_session.commit()


def test_mode_b_charges_and_caps(
    db_session, job_env, fake_retrieve, monkeypatch  # noqa: F811
):
    from engine.retrievers.chatgpt_web import WebRetrievalOutcome
    from worker.jobs import run_mode_b

    async def _fake(persona_prompt, query_text, *, headless, timeout_s,
                    executable_path=None, env=None):
        return WebRetrievalOutcome(text="a", citations=[], html_fragment="<p/>", latency_ms=1)

    monkeypatch.setattr("engine.retrievers.chatgpt_web.retrieve", _fake)
    monkeypatch.setenv("CHATGPT_WEB_RATE_PER_MIN", "100000")
    monkeypatch.setenv("SCRAPE_COST_PER_PAGE_USD", "0.10")
    from api.config import get_settings

    get_settings.cache_clear()

    # 5 queries × 1 web surface = 5 scrapes at $0.10 = $0.50 of demand, but the
    # cap is $0.25 → only 2 should run, the rest withheld.
    tenant = make_tenant(db_session, queries=5, personas=1)
    tenant.monthly_spend_cap_usd = 0.25
    add_web_surface(db_session, tenant)
    _b_only(db_session, tenant)
    db_session.add(tenant)
    db_session.commit()

    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)

    from api.models import Run

    run = db_session.get(Run, run_id)
    assert run is not None
    completed = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.status == ResultStatus.ok)
    ).all()
    # Cap stops spending once reached: 2 scrapes ($0.20) fit under $0.25, a 3rd
    # would cross it.
    assert len(completed) == 2
    assert run.counts.get("withheld_by_cap") == 3
    assert run.counts.get("capped") is True
    assert run.status == RunStatus.capped
    assert run.cost_usd == 0.20
