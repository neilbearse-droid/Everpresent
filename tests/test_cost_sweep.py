"""Cost fixes from the November 2026 sweep: paid work is never bought twice
(entity extraction on reprocess), a call the provider billed but that gave
no answer is booked, the nightly crawl spends only where it must, and the
scrape queue interleaves its engines."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from api.engine_weights import DEFAULT_ENGINE_WEIGHTS, samples_for_surface
from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    PagePresence,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SpendEntry,
    SurfaceCode,
    Tenant,
    TenantStatus,
    UntrackedMention,
    utcnow,
)
from engine.retrievers.openai_api import (
    BilledFailure,
    ParsedResponse,
    should_retry_transport,
)
from tests.test_runs import _pending_run, job_env, make_tenant  # noqa: F401

# --- entity extraction is paid for once --------------------------------------


def _extraction_tenant(db_session, texts: list[str]):
    tenant = Tenant(
        name="GoDaddy", slug="gd", ai_processing_approved=True,
        entity_extraction_enabled=True,
        approved_utility_models=["claude-haiku-4-5-20251001"],
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db_session.add(Competitor(tenant_id=tenant.id, name="Wix", aliases=[], domains=["wix.com"]))
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    for i, _text in enumerate(texts):
        db_session.add(Result(
            run_id=run.id, tenant_id=tenant.id, query_text=f"q{i}", persona_name="p",
            surface=SurfaceCode.openai_api, variant=ResultVariant.search,
            status=ResultStatus.ok, raw_uri=f"inline-{i}",
        ))
    db_session.commit()
    return tenant, run


@pytest.fixture
def extraction(monkeypatch):
    from api.config import get_settings

    calls: list[str] = []
    state = {"texts": {}, "fail": False}

    def _complete(prompt, **_k):
        if state["fail"]:
            raise RuntimeError("boom")
        calls.append(prompt)
        return '["GoDaddy", "Wix", "Square", "Toast"]'

    monkeypatch.setattr(
        "api.processing_service._envelope",
        lambda result, session: {"parsed_text": state["texts"][result.raw_uri]},
    )
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    monkeypatch.setattr("engine.llm.router.complete", _complete)
    return calls, state


def test_reprocess_does_not_buy_extraction_again(db_session, extraction):
    from api.processing_service import process_run

    calls, state = extraction
    tenant, run = _extraction_tenant(db_session, ["a", "b"])
    state["texts"] = {"inline-0": "Try Square.", "inline-1": "Try Toast."}

    assert process_run(db_session, run)["untracked_mentions"] == 4
    db_session.commit()
    assert len(calls) == 2
    cost_after_first = run.cost_usd

    # Reprocessing keeps the rows and makes no new call, and books no new cost.
    assert process_run(db_session, run)["untracked_mentions"] == 4
    db_session.commit()
    assert len(calls) == 2
    assert run.cost_usd == cost_after_first
    assert len(db_session.exec(select(UntrackedMention)).all()) == 4


def test_identical_answers_share_one_extraction_call(db_session, extraction):
    from api.processing_service import process_run

    calls, state = extraction
    _tenant, run = _extraction_tenant(db_session, ["a", "b", "c"])
    state["texts"] = {"inline-0": "Same.", "inline-1": "Same.", "inline-2": "Other."}
    assert process_run(db_session, run)["untracked_mentions"] == 6
    assert len(calls) == 2


def test_failed_extraction_is_retried_and_a_newly_tracked_name_is_dropped(
        db_session, extraction):
    from api.processing_service import process_run

    calls, state = extraction
    tenant, run = _extraction_tenant(db_session, ["a"])
    state["texts"] = {"inline-0": "Try Square."}
    state["fail"] = True
    assert process_run(db_session, run)["untracked_mentions"] == 0
    assert (run.cost_usd or 0.0) == 0.0  # a call that failed is not booked

    state["fail"] = False
    assert process_run(db_session, run)["untracked_mentions"] == 2
    db_session.commit()
    assert len(calls) == 1

    # Square becomes a tracked competitor: its row goes, with no new call.
    db_session.add(Competitor(tenant_id=tenant.id, name="Square", aliases=[], domains=[]))
    db_session.commit()
    assert process_run(db_session, run)["untracked_mentions"] == 1
    assert len(calls) == 1


def test_extraction_on_an_older_months_run_goes_to_the_ledger(db_session, extraction):
    from api.processing_service import process_run

    _calls, state = extraction
    tenant, run = _extraction_tenant(db_session, ["a"])
    state["texts"] = {"inline-0": "Try Square."}
    run.created_at = utcnow() - timedelta(days=70)
    db_session.add(run)
    db_session.commit()
    process_run(db_session, run)
    db_session.commit()
    assert (run.cost_usd or 0.0) == 0.0
    entry = db_session.exec(select(SpendEntry)).one()
    assert entry.kind == "entity_extraction" and entry.cost_usd > 0


# --- billed failures and timeouts --------------------------------------------


def test_a_billed_call_with_no_answer_is_booked_on_the_run(db_session, job_env,  # noqa: F811
                                                            monkeypatch):
    from worker.jobs import run_mode_a

    async def _empty(persona_prompt, query_text, **_k):
        raise BilledFailure(
            "OpenAI response incomplete with no text (max_output_tokens)",
            ParsedResponse(text="", input_tokens=2000, output_tokens=1200,
                           web_search_calls=1, model="gpt-5.6-terra"),
        )

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _empty)
    t = make_tenant(db_session, queries=1, personas=1)
    t.plan = "monitor"  # one cell: no twin, no probe
    db_session.add(t)
    db_session.commit()
    run_id = _pending_run(db_session, t)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    db_session.refresh(run)
    assert run.counts["failed"] == 1 and run.counts["billed_failures"] == 1
    assert run.cost_usd > 0
    assert run.counts["cost:openai_api"] == run.cost_usd
    assert db_session.exec(select(Result)).one().status == ResultStatus.error


def test_read_timeouts_get_one_retry_and_connect_errors_the_full_ladder():
    read = httpx.ReadTimeout("slow")
    assert should_retry_transport(read, 1, 3) is True
    assert should_retry_transport(read, 2, 3) is False  # sent twice already: may bill each
    conn = httpx.ConnectError("refused")
    assert should_retry_transport(conn, 2, 3) is True
    assert should_retry_transport(conn, 3, 3) is False


def test_openai_stops_after_two_read_timeouts(monkeypatch):
    from engine.retrievers import openai_api

    async def _instant(_s):
        return None

    calls = []

    async def _timeout(self, *a, **k):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(asyncio, "sleep", _instant)
    monkeypatch.setattr(httpx.AsyncClient, "post", _timeout)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(openai_api.retrieve("", "q", api_key="k", model="gpt-4o"))
    assert len(calls) == 2


# --- sampling, probes, scrape order ------------------------------------------


def test_a_costly_engine_needs_twice_the_weight_for_each_sample():
    assert samples_for_surface("gemini_api", 3, DEFAULT_ENGINE_WEIGHTS) == 1
    assert samples_for_surface("gemini_api", 3, {**DEFAULT_ENGINE_WEIGHTS, "gemini": 20}) == 2
    assert samples_for_surface("gemini_api", 3, {**DEFAULT_ENGINE_WEIGHTS, "gemini": 40}) == 3


def test_shard_probes_run_one_tier_below_premium():
    from worker.jobs import _probe_tier

    assert _probe_tier("premium") == "standard"
    assert _probe_tier("standard") == "standard"
    assert _probe_tier("configured") == "configured"


def test_mode_b_work_alternates_between_engines():
    from worker.jobs import _BWorkItem, _interleave_by_surface

    def item(q, s):
        return _BWorkItem(None, q, None, "p", "", "", s)

    work = [item("q1", "chatgpt_web"), item("q2", "chatgpt_web"), item("q3", "chatgpt_web"),
            item("q1", "copilot_web"), item("q2", "copilot_web"), item("q1", "google_aio")]
    out = [(w.surface, w.query_text) for w in _interleave_by_surface(work)]
    assert out == [("chatgpt_web", "q1"), ("copilot_web", "q1"), ("google_aio", "q1"),
                   ("chatgpt_web", "q2"), ("copilot_web", "q2"), ("chatgpt_web", "q3")]


# --- nightly crawl -----------------------------------------------------------

OK_HTML = "<html><body><h1>Best CRM</h1><p>Globex is a fine choice.</p></body></html>"


def _crawl_tenant(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Competitor(tenant_id=tid, name="Globex", domains=["globex.com"]))
    db_session.add(Query(tenant_id=tid, text="best crm", corpus_tag="crm"))
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=tid, query_text="best crm", persona_name="p",
               surface=SurfaceCode.openai_api, variant=ResultVariant.search,
               status=ResultStatus.ok)
    db_session.add(r)
    db_session.commit()
    for url, domain, cat in (("https://g2.com/best-crm", "g2.com", "other"),
                             ("https://acme.com/crm", "acme.com", "brand")):
        db_session.add(Citation(result_id=r.id, tenant_id=tid, url=url, domain=domain,
                                source_category=cat))
    db_session.commit()
    return tid


def test_nightly_crawl_rereads_own_pages_but_not_fresh_third_party_ones(db_session,
                                                                         monkeypatch):
    from worker import page_crawl

    tid = _crawl_tenant(db_session)
    fetched: list[str] = []

    def _fetch(client, url):
        fetched.append(url)
        return {"html": OK_HTML, "http_status": 200}

    monkeypatch.setattr(page_crawl, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(page_crawl, "crawl_page", _fetch)

    page_crawl.crawl_power_pages(tid, True)
    assert sorted(fetched) == ["https://acme.com/crm", "https://g2.com/best-crm"]

    fetched.clear()
    page_crawl.crawl_power_pages(tid, True)  # next night
    assert fetched == ["https://acme.com/crm"]

    # A week on, the third-party page is due again; on demand reads everything.
    row = db_session.exec(select(PagePresence).where(
        PagePresence.url == "https://g2.com/best-crm")).one()
    row.fetched_at = utcnow() - timedelta(days=8)
    db_session.add(row)
    db_session.commit()
    fetched.clear()
    page_crawl.crawl_power_pages(tid, True)
    assert len(fetched) == 2
    fetched.clear()
    page_crawl.crawl_power_pages(tid)
    assert len(fetched) == 2
    assert db_session.exec(select(SpendEntry)).all() == []  # nothing paid was used


def test_crawl_uses_the_proxy_only_when_refused_and_reuses_brave(db_session, monkeypatch):
    from api.config import get_settings
    from worker import page_crawl

    tid = _crawl_tenant(db_session)
    monkeypatch.setattr(get_settings(), "scrape_proxy_url", "http://user:pw@proxy.example:8000")
    monkeypatch.setattr(get_settings(), "brave_search_api_key", "brave-key")
    monkeypatch.setattr(page_crawl.time, "sleep", lambda _s: None)
    brave_calls: list[str] = []
    monkeypatch.setattr(page_crawl, "brave_indexed",
                        lambda key, url: brave_calls.append(url) or True)
    # The direct fetch always comes first; a second fetch of the same URL in
    # one crawl is the proxied retry.
    tries: dict[str, int] = {}

    def _fetch(client, url):
        tries[url] = tries.get(url, 0) + 1
        if "g2.com" in url and tries[url] == 1:
            return {"html": "", "http_status": 403}
        return {"html": OK_HTML, "http_status": 200}

    monkeypatch.setattr(page_crawl, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(page_crawl, "crawl_page", _fetch)

    page_crawl.crawl_power_pages(tid)
    assert tries == {"https://acme.com/crm": 1,       # answered directly: no proxy
                     "https://g2.com/best-crm": 2}    # refused directly: proxied once
    g2 = db_session.exec(select(PagePresence).where(
        PagePresence.url == "https://g2.com/best-crm")).one()
    assert g2.status == "ok"
    assert brave_calls == ["https://acme.com/crm"]
    entry = db_session.exec(select(SpendEntry)).one()
    assert entry.kind == "page_crawl"
    assert entry.cost_usd == pytest.approx(0.002 + 0.005)

    page_crawl.crawl_power_pages(tid)  # the Brave lookup is a day old: reused
    assert len(brave_calls) == 1
    own = db_session.exec(select(PagePresence).where(
        PagePresence.url == "https://acme.com/crm")).one()
    assert own.features["brave_indexed"] is True and own.features["brave_checked_at"]


def test_nightly_crawl_skips_archived_and_idle_tenants(db_session, monkeypatch):
    from worker.scheduler import tick

    enqueued: list[tuple] = []

    class FakeQueue:
        def enqueue(self, *args, **kwargs):
            enqueued.append(args)

    monkeypatch.setattr("api.queue.get_queue", lambda name="default": FakeQueue())
    now = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    ids = {}
    for slug, status, age_days in (("live", TenantStatus.active, 2),
                                   ("gone", TenantStatus.archived, 2),
                                   ("idle", TenantStatus.active, 60)):
        t = Tenant(name=slug, slug=slug, status=status)
        db_session.add(t)
        db_session.commit()
        ids[slug] = t.id
        db_session.add(Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete,
                           created_at=now - timedelta(days=age_days)))
    db_session.commit()

    tick(db_session, now)
    crawls = [a for a in enqueued if a[0] == "worker.page_crawl.crawl_power_pages"]
    assert crawls == [("worker.page_crawl.crawl_power_pages", ids["live"], True)]
