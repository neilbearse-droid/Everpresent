"""Natural search-routing probe (§AEO-plan M2): the un-forced request shape,
the sampled dispatch, and the routing report."""

from sqlmodel import select

from api.dashboards_service import routing_report
from api.models import (
    BrandProfile,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from engine.retrievers.openai_api import build_request_body
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401


def test_forced_vs_natural_request_body():
    forced = build_request_body("p", "q", model="gpt-5.6-terra", web_search=True)
    assert forced["tool_choice"] == {"type": "web_search"}

    natural = build_request_body("p", "q", model="gpt-5.6-terra", web_search=True,
                                 force_search=False)
    # Tool offered, but the model decides → no tool_choice.
    assert natural["tools"] == [{"type": "web_search"}]
    assert "tool_choice" not in natural


def _seed(db, *, variant, surface, qtext, searches):
    tenant_id = db.exec(select(Tenant)).first().id
    run = Run(tenant_id=tenant_id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    r = Result(run_id=run.id, tenant_id=tenant_id, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant(variant),
               status=ResultStatus.ok, web_search_calls=searches)
    db.add(r)
    db.commit()


def test_routing_report_uses_probe_for_forced_surface(db_session):
    tenant = Tenant(name="Smith", slug="smith")
    db_session.add(tenant)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="Smith", domains=["s.ca"]))
    db_session.commit()

    # OpenAI is forced: its search variant always searched, but the natural
    # probe reveals one prompt that did NOT trigger search.
    _seed(db_session, variant="search", surface="openai_api", qtext="q1", searches=1)
    _seed(db_session, variant="natural", surface="openai_api", qtext="q1", searches=1)
    _seed(db_session, variant="natural", surface="openai_api", qtext="q2", searches=0)
    # Gemini is not forced: its search variant reveals routing directly.
    _seed(db_session, variant="search", surface="gemini_api", qtext="q1", searches=0)

    rep = routing_report(db_session, tenant.id)
    engines = {e["surface"]: e for e in rep["engines"]}
    # OpenAI: measured from the 2 probed prompts (search variant ignored),
    # 1 of 2 searched → 50%.
    assert engines["openai_api"]["measured"] == 2
    assert engines["openai_api"]["searched"] == 1
    assert engines["openai_api"]["search_rate"] == 50.0
    assert engines["openai_api"]["from_probe"] is True
    # Gemini: from its own search variant, 0/1 searched.
    assert engines["gemini_api"]["measured"] == 1
    assert engines["gemini_api"]["searched"] == 0
    assert engines["gemini_api"]["from_probe"] is False


def test_forced_surfaces_stay_in_sync_with_worker_registry():
    # api.dashboards_service._FORCED_SEARCH_SURFACES is a hand-maintained copy
    # of which worker adapters force search. If a new forced surface is added
    # to the worker registry without updating the dashboard set, routing_report
    # would read the (forced, uninformative) search variant instead of the M2
    # natural probe and silently report 100% search rates. Couple them here.
    from api.dashboards_service import _FORCED_SEARCH_SURFACES
    from worker.jobs import A_ADAPTERS

    assert _FORCED_SEARCH_SURFACES == {
        s for s, a in A_ADAPTERS.items() if a.forces_search
    }


def test_natural_probe_dispatched_for_openai(
    db_session, job_env, fake_retrieve, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_a

    monkeypatch.setenv("NATURAL_PROBE_FRACTION", "1.0")  # probe every query
    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", lambda run_id: None)
    from api.config import get_settings

    get_settings.cache_clear()

    tenant = make_tenant(db_session, "smith", queries=2, personas=1)
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="Smith", domains=["s.ca"]))
    db_session.commit()

    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)

    natural = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.variant == ResultVariant.natural)
    ).all()
    # openai_api is the only forced surface enabled → 2 queries × 1 probe each.
    assert len(natural) == 2
    assert all(r.surface == SurfaceCode.openai_api for r in natural)
