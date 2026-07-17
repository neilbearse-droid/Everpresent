"""Mode B pipeline: mode_set derivation, trigger routing, A→B chaining with a
single finalize, rate-limited dispatch with a faked adapter, and the
side-by-side data reaching queries-intel."""

import json
from pathlib import Path

import pytest
from sqlmodel import select

from api.models import (
    Citation,
    Result,
    Run,
    RunStatus,
    SurfaceCode,
    TenantSurface,
    User,
)
from engine.retrievers.chatgpt_web import WebRetrievalOutcome, parse_assistant_html
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "chatgpt_web_message.html"
).read_text(encoding="utf-8")


def add_web_surface(db_session, tenant):
    tenant.approved_surfaces = [
        SurfaceCode.openai_api.value,
        SurfaceCode.chatgpt_web.value,
    ]
    db_session.add(tenant)
    db_session.add(
        TenantSurface(tenant_id=tenant.id, code=SurfaceCode.chatgpt_web, enabled=True)
    )
    db_session.commit()
    return tenant


@pytest.fixture()
def superadmin(db_session):
    user = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def as_superadmin(login, superadmin):
    login(superadmin)
    return superadmin


@pytest.fixture()
def fake_web_retrieve(monkeypatch):
    text, citations = parse_assistant_html(FIXTURE_HTML)

    async def _fake(persona_prompt, query_text, *, headless, timeout_s,
                    executable_path=None, env=None):
        return WebRetrievalOutcome(
            text=text,
            citations=list(citations),
            html_fragment=FIXTURE_HTML,
            latency_ms=1234,
        )

    monkeypatch.setattr("engine.retrievers.chatgpt_web.retrieve", _fake)
    monkeypatch.setenv("CHATGPT_WEB_RATE_PER_MIN", "100000")
    from api.config import get_settings

    get_settings.cache_clear()


def test_mode_set_covers_both_modes(client, as_superadmin, db_session, monkeypatch):
    enq_a, enq_b = [], []
    monkeypatch.setattr("api.queue.enqueue_run", enq_a.append)
    monkeypatch.setattr("api.queue.enqueue_run_mode_b", enq_b.append)
    tenant = make_tenant(db_session)
    add_web_surface(db_session, tenant)

    run = client.post("/api/admin/tenants/smith/runs").json()
    assert sorted(run["surface_set"]) == ["chatgpt_web", "openai_api"]
    assert run["mode_set"] == ["A", "B"]
    # A leads; B is chained by the A job, not double-enqueued at trigger time.
    assert enq_a == [run["id"]] and enq_b == []


def test_b_only_tenant_goes_straight_to_scrape_queue(
    client, as_superadmin, db_session, monkeypatch
):
    enq_a, enq_b = [], []
    monkeypatch.setattr("api.queue.enqueue_run", enq_a.append)
    monkeypatch.setattr("api.queue.enqueue_run_mode_b", enq_b.append)
    tenant = make_tenant(db_session)
    add_web_surface(db_session, tenant)
    api_surface = db_session.exec(
        select(TenantSurface).where(
            TenantSurface.tenant_id == tenant.id,
            TenantSurface.code == SurfaceCode.openai_api,
        )
    ).one()
    api_surface.enabled = False
    db_session.add(api_surface)
    db_session.commit()

    run = client.post("/api/admin/tenants/smith/runs").json()
    assert run["mode_set"] == ["B"]
    assert enq_a == [] and enq_b == [run["id"]]


def test_a_chains_into_b_and_b_finalizes(
    db_session, job_env, fake_retrieve, fake_web_retrieve, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_a, run_mode_b

    chained: list[int] = []
    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", chained.append)

    tenant = make_tenant(db_session)  # 2 queries × 2 personas
    add_web_surface(db_session, tenant)
    run_id = _pending_run(db_session, tenant)

    run_mode_a(run_id)
    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.running  # not finalized yet
    assert chained == [run_id]

    run_mode_b(run_id)
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete
    # A: 4 search + 2 nosearch; B: one per (query, surface) = 2. All complete.
    assert run.counts["planned"] == 8
    assert run.counts["completed"] == 8
    assert run.counts["failed"] == 0

    b_results = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.mode == "B")
    ).all()
    assert len(b_results) == 2
    for result in b_results:
        assert result.surface == SurfaceCode.chatgpt_web
        assert result.variant == "search"
        assert result.latency_ms == 1234
        envelope = json.loads((job_env / result.raw_uri).read_text())
        assert envelope["model"] == "chatgpt-web"
        assert envelope["response"]["html"] == FIXTURE_HTML
        assert "Smith School of Business" in envelope["parsed_text"]

    # B citations stored alongside A's; both modes feed processing.
    b_citation_domains = {
        c.domain
        for c in db_session.exec(select(Citation)).all()
        if c.result_id in {r.id for r in b_results}
    }
    assert b_citation_domains == {"ft.com", "smith.queensu.ca"}
    # Processing ran once, over both modes (2 queries classified from A's
    # twins; mentions cover A search results + B results = 4 + 2).
    assert run.counts["classified_queries"] == 2
    assert run.counts["mentions"] == 6


def test_failed_scrapes_are_data(db_session, job_env, fake_retrieve, monkeypatch):  # noqa: F811
    from worker.jobs import run_mode_b

    async def _blocked(persona_prompt, query_text, *, headless, timeout_s,
                       executable_path=None, env=None):
        raise TimeoutError("cloudflare interstitial never cleared")

    monkeypatch.setattr("engine.retrievers.chatgpt_web.retrieve", _blocked)
    monkeypatch.setenv("CHATGPT_WEB_RATE_PER_MIN", "100000")
    from api.config import get_settings

    get_settings.cache_clear()

    tenant = make_tenant(db_session, queries=1, personas=1)
    add_web_surface(db_session, tenant)
    api_surface = db_session.exec(
        select(TenantSurface).where(
            TenantSurface.tenant_id == tenant.id,
            TenantSurface.code == SurfaceCode.openai_api,
        )
    ).one()
    api_surface.enabled = False
    db_session.add(api_surface)
    db_session.commit()

    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)
    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.failed
    result = db_session.exec(select(Result).where(Result.run_id == run_id)).one()
    assert result.status == "error" and "cloudflare" in (result.error or "")


def test_queries_intel_shows_both_modes(
    client, login, db_session, job_env, fake_retrieve, fake_web_retrieve, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_a, run_mode_b

    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", lambda run_id: None)
    tenant = make_tenant(db_session)
    add_web_surface(db_session, tenant)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)
    run_mode_b(run_id)

    member = User(email="m@smith.example", clerk_user_id="user_m")
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)
    login(member, org_id="org_smith")

    body = client.get("/api/tenant/queries-intel").json()
    for query in body["queries"]:
        modes = {r["mode"] for r in query["latest_results"].values()}
        assert modes == {"A", "B"}  # the side-by-side comparison, per query
        assert query["latest_results"]["chatgpt_web"]["brand_mentioned"] is True
