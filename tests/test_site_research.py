"""Site searches (where engines check facts) and the primary-sources play."""

from sqlmodel import select

from api.config import get_settings
from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    Query,
    Recommendation,
    Result,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from engine.processing.citations import classify_source_type


def _tenant(db) -> int:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    assert t.id is not None
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.add(Competitor(tenant_id=t.id, name="Rival", aliases=[], domains=["rival.com"]))
    db.add(Query(tenant_id=t.id, text="best crm"))
    db.add(Query(tenant_id=t.id, text="Is Acme good?", branded=True))
    db.commit()
    return t.id


def _result(db, tid, qtext, subs, variant=ResultVariant.search) -> Result:
    run = db.exec(select(Run).where(Run.tenant_id == tid)).first()
    if run is None:
        run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
        db.add(run)
        db.commit()
    assert run.id is not None
    r = Result(run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode.openai_api, variant=variant, fanout_queries=subs)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_site_searches_split_yours_rivals_and_others(db_session):
    from api.site_search_service import site_searches, site_targets

    assert site_targets('"renewal price" site:https://www.Rival.com/pricing') == (
        ["rival.com"], "renewal price")
    tid = _tenant(db_session)
    _result(db_session, tid, "best crm", [
        "site:rival.com pricing", "site:help.rival.com renewal price",
        "site:acme.com pricing OR site:rival.com pricing", "best crm 2026",
        "site:g2.com crm reviews"])
    _result(db_session, tid, "best crm", ["site:rival.com pricing"], ResultVariant.natural)
    # A branded question sends engines to your site by design: not counted.
    _result(db_session, tid, "Is Acme good?", ["site:acme.com reviews"] * 5)
    # The no-search twin never searched.
    _result(db_session, tid, "best crm", ["site:acme.com x"], ResultVariant.nosearch)

    s = site_searches(db_session, tid)
    assert (s["owned"], s["rivals"], s["other"], s["site_searches"]) == (1, 4, 1, 6)
    assert s["sub_searches"] == 6
    by = {t["name"]: t for t in s["targets"]}
    assert by["Rival"]["domains"] == ["help.rival.com", "rival.com"]
    assert by["Rival"]["top_asks"][0] == "pricing"
    assert s["looked_for"] == [{"text": "pricing", "count": 1, "engines": ["ChatGPT"]}]


def test_site_search_play_fires_only_on_a_real_gap(db_session):
    from api.recommendations_service import _site_search_play

    tid = _tenant(db_session)
    _result(db_session, tid, "best crm", ["site:rival.com pricing"] * 4 + ["site:acme.com plans"])
    assert _site_search_play(db_session, tid) == []  # under the minimum
    _result(db_session, tid, "best crm", ["site:rival.com refund policy"] * 3)
    (play,) = _site_search_play(db_session, tid)
    assert play.gap_ref == "site_search:rivals" and "Rival's sites 7 times" in play.action_text
    assert "“pricing”" in play.action_text and play.link == "/dashboard/pages"


def test_research_sources_are_their_own_type():
    for d in ("pubmed.ncbi.nlm.nih.gov", "www.cdc.gov", "stanford.edu", "nature.com",
              "ec.europa.eu", "ons.gov.uk", "doi.org"):
        assert classify_source_type(d) == "research", d
    for d, kind in (("webmd.com", "publisher"), ("reddit.com", "community"),
                    ("en.wikipedia.org", "encyclopedia"), ("governmentjobs.com", "publisher")):
        assert classify_source_type(d) == kind, d


def test_research_play_needs_a_real_share(db_session):
    from api.recommendations_service import _research_play

    tid = _tenant(db_session)
    r = _result(db_session, tid, "best crm", [])
    for d in ("pubmed.ncbi.nlm.nih.gov", "nih.gov", "cdc.gov", "nature.com"):
        db_session.add(Citation(result_id=r.id, tenant_id=tid, url=f"https://{d}/x", domain=d))
    for i in range(10):
        db_session.add(Citation(result_id=r.id, tenant_id=tid, url=f"https://pub{i}.com/x",
                                domain=f"pub{i}.com"))
    db_session.commit()
    (play,) = _research_play(db_session, tid)
    assert play.gap_ref == "sources:research" and "4 of 14 citations" in play.action_text

    # A couple of research links among many publishers is not a pattern.
    tid2_t = Tenant(name="B", slug="b")
    db_session.add(tid2_t)
    db_session.commit()
    assert tid2_t.id is not None
    db_session.add(Query(tenant_id=tid2_t.id, text="q"))
    r2 = _result(db_session, tid2_t.id, "q", [])
    db_session.add(Citation(result_id=r2.id, tenant_id=tid2_t.id, url="https://nih.gov/x",
                            domain="nih.gov"))
    for i in range(30):
        db_session.add(Citation(result_id=r2.id, tenant_id=tid2_t.id,
                                url=f"https://p{i}.com/x", domain=f"p{i}.com"))
    db_session.commit()
    assert _research_play(db_session, tid2_t.id) == []


def test_demo_client_shows_the_site_search_gap(db_session, monkeypatch, tmp_path):
    from api.demo_client import SLUG, build_demo_client

    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    build_demo_client(db_session)
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == SLUG)).one()
    play = db_session.exec(select(Recommendation).where(
        Recommendation.tenant_id == tenant.id,
        Recommendation.gap_ref == "site_search:rivals")).one()
    assert "Siteforge and Pagecraft" in play.action_text
