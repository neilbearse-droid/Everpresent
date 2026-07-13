"""M6 end-to-end: AIO capture in the run pipeline, google_aio_* on
classifications, the recommendation matrix (web_search / training / aio
branches), auto-resolve, and the dashboard tiles."""

import pytest
from sqlmodel import select

from api.models import (
    BrandProfile,
    QueryClassification,
    Recommendation,
    Result,
    Run,
    RunStatus,
    SurfaceCode,
    TenantSurface,
    User,
)
from api.processing_service import process_run
from engine.retrievers.google_aio import AIOCaptureSummary, AIOOutcome
from engine.retrievers.openai_api import ParsedCitation
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)

AIO_TEXT = (
    "For an MBA in Canada, Smith School of Business at Queen's University is a "
    "strong one-year option; Rotman and Ivey are frequently shortlisted."
)


@pytest.fixture()
def fake_aio(monkeypatch):
    async def _fake(query_text, *, geo, provider, serpapi_key, headless, timeout_s,
                    executable_path=None):
        return AIOOutcome(
            summary=AIOCaptureSummary(
                aio_present=True, aio_position_index=0, aio_text_len=len(AIO_TEXT),
                expanded=False, organic_count=8,
            ),
            aio_text=AIO_TEXT,
            aio_html="<div>aio</div>",
            page_html="<html>serp</html>",
            citations=[
                ParsedCitation(url="https://smith.queensu.ca/programs/mba", title="Smith MBA"),
                ParsedCitation(url="https://www.ft.com/mba-rankings/canada", title="FT"),
            ],
            latency_ms=555,
        )

    monkeypatch.setattr("engine.retrievers.google_aio.capture", _fake)
    monkeypatch.setenv("GOOGLE_AIO_RATE_PER_MIN", "100000")
    from api.config import get_settings

    get_settings.cache_clear()


def make_aio_tenant(db_session, *, brand_name="Acme Benefits", brand_domains=None):
    """A tenant whose brand does NOT appear in the fixture answers, so every
    query is a gap. AIO + API surfaces enabled."""
    tenant = make_tenant(db_session, "acme", org="org_acme", queries=2, personas=1)
    assert tenant.id is not None
    tenant.approved_surfaces = [SurfaceCode.openai_api.value, SurfaceCode.google_aio.value]
    db_session.add(tenant)
    db_session.add(
        TenantSurface(tenant_id=tenant.id, code=SurfaceCode.google_aio, enabled=True)
    )
    db_session.add(
        BrandProfile(
            tenant_id=tenant.id,
            brand_name=brand_name,
            aliases=[],
            domains=brand_domains or ["acme.example"],
        )
    )
    db_session.commit()
    return tenant


def _run_both(db_session, tenant, monkeypatch):
    from worker.jobs import run_mode_a, run_mode_b

    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", lambda run_id: None)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)
    run_mode_b(run_id)
    return run_id


def test_aio_capture_stored_and_classified(
    db_session, job_env, fake_retrieve, fake_aio, monkeypatch  # noqa: F811
):
    tenant = make_aio_tenant(db_session)
    run_id = _run_both(db_session, tenant, monkeypatch)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete

    aio_results = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.surface == "google_aio")
    ).all()
    assert len(aio_results) == 2  # one per query, no persona
    for result in aio_results:
        assert result.persona_name == "(serp)"
        assert result.mode == "B"
        import json

        envelope = json.loads((job_env / result.raw_uri).read_text())
        assert envelope["response"]["aio_summary"]["aio_present"] is True
        assert envelope["response"]["page_html"] == "<html>serp</html>"  # §6.3
        assert "Smith School of Business" in envelope["parsed_text"]

    classifications = db_session.exec(select(QueryClassification)).all()
    aio_classified = [c for c in classifications if c.google_aio_triggered]
    assert len(aio_classified) == 2
    for c in aio_classified:
        assert c.google_aio_source_type == "aio_plus_organic"  # top, modest size
        assert c.google_aio_confidence == 0.7
        assert "smith.queensu.ca" in c.google_aio_signals["cited_domains"]
        # Orthogonal: the web-search bucket from the dual-query diff is intact.
        assert c.web_search_likelihood == "very_likely"


def test_recommendation_matrix_branches(
    db_session, job_env, fake_retrieve, fake_aio, monkeypatch  # noqa: F811
):
    tenant = make_aio_tenant(db_session)
    _run_both(db_session, tenant, monkeypatch)

    recs = db_session.exec(select(Recommendation)).all()
    by_branch: dict[str, list[Recommendation]] = {}
    for rec in recs:
        by_branch.setdefault(rec.branch, []).append(rec)
    # Brand absent from answers (web_search branch: bucket very_likely) and
    # absent from AIO citations (aio branch) — for each of the 2 queries.
    assert len(by_branch["web_search"]) == 2
    assert len(by_branch["aio"]) == 2
    assert "training" not in by_branch
    assert all(r.status == "open" for r in recs)
    assert any("AI Overview" in r.action_text for r in by_branch["aio"])


def test_gap_close_resolves_and_hand_statuses_survive(
    db_session, job_env, fake_retrieve, fake_aio, monkeypatch  # noqa: F811
):
    tenant = make_aio_tenant(db_session)
    run_id = _run_both(db_session, tenant, monkeypatch)
    recs = db_session.exec(select(Recommendation)).all()
    assert recs and all(r.status == "open" for r in recs)

    # A human dismisses one; then the brand is fixed (matches the answers)
    # and the run reprocesses: gaps close.
    dismissed = recs[0]
    dismissed.status = "dismissed"
    db_session.add(dismissed)
    brand = db_session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant.id)
    ).one()
    brand.brand_name = "Smith School of Business"
    brand.domains = ["smith.queensu.ca"]
    db_session.add(brand)
    db_session.commit()

    run = db_session.get(Run, run_id)
    assert run is not None
    process_run(db_session, run)

    db_session.expire_all()
    for rec in db_session.exec(select(Recommendation)).all():
        if rec.id == dismissed.id:
            assert rec.status == "dismissed"  # human decisions survive
        else:
            assert rec.status == "resolved"


def test_recommendations_endpoint_and_isolation(
    client, login, db_session, job_env, fake_retrieve, fake_aio, monkeypatch  # noqa: F811
):
    tenant = make_aio_tenant(db_session)
    _run_both(db_session, tenant, monkeypatch)
    make_tenant(db_session, "other", org="org_other", queries=1, personas=1)

    member = User(email="m@acme.example", clerk_user_id="user_acme")
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    login(member, org_id="org_acme")
    recs = client.get("/api/tenant/recommendations").json()
    assert len(recs) == 4
    rec_id = recs[0]["id"]
    patched = client.patch(f"/api/tenant/recommendations/{rec_id}", json={"status": "in_progress"})
    assert patched.status_code == 200 and patched.json()["status"] == "in_progress"

    # AIO tile + citations screen data
    overview = client.get("/api/tenant/overview").json()
    assert overview["aio"] == {
        "queries_measured": 2,
        "queries_with_aio": 2,
        "aio_share_pct": 100.0,
        "brand_cited_in_aio": 0,  # acme.example is never an AIO source
        "source_types": {"aio_plus_organic": 2},
    }
    citations = client.get("/api/tenant/citations-intel").json()
    domains = {d["domain"]: d for d in citations["domains"]}
    assert "google_aio" in domains["smith.queensu.ca"]["surfaces"]
    assert citations["aio"]["aio_share_pct"] == 100.0

    # Cross-tenant: members of the other org see nothing and can't patch.
    login(member, org_id="org_other")
    assert client.get("/api/tenant/recommendations").json() == []
    assert (
        client.patch(f"/api/tenant/recommendations/{rec_id}", json={"status": "done"}).status_code
        == 404
    )
