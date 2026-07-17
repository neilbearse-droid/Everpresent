"""Citation-gap target list + per-gap content briefs (panel #4 + #1), over
hand-built data so the third-party-source filter and brief assembly are
exercised deterministically."""

from api.dashboards_service import action_plan
from api.models import (
    BrandProfile,
    Citation,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)


def _result(db, run_id, tid, qtext, surface, variant, rhash=""):
    r = Result(run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant(variant),
               status=ResultStatus.ok, response_hash=rhash)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_targets_and_brief_for_a_content_gap(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="best crm", corpus_tag="crm"))
    db_session.add(Query(tenant_id=tid, text="crm for startups", corpus_tag="crm"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    run_id = run.id

    # Search answer: rival present, brand absent, cites a third-party source + rival site.
    s = _result(db_session, run_id, tid, "best crm", "openai_api", "search")
    db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                           entity_name="Globex", position=0, rank=1))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://g2.com/crm",
                            domain="g2.com", source_category="other"))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://globex.com",
                            domain="globex.com", source_category="competitor"))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://acme.com/x",
                            domain="acme.com", source_category="brand"))
    # Training-only twin knows the brand -> content gap (not knowledge gap).
    ns = _result(db_session, run_id, tid, "best crm", "openai_api", "nosearch")
    db_session.add(Mention(result_id=ns.id, tenant_id=tid, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    db_session.commit()

    plan = action_plan(db_session, tid)

    # #4 target list: only the pitchable third-party source; rival + owned excluded.
    target_domains = [t["domain"] for t in plan["targets"]]
    assert target_domains == ["g2.com"]
    g2 = plan["targets"][0]
    assert g2["competitor_assoc"] == 1 and g2["already_citing_you"] is False

    # #1 content brief for the gap query.
    assert len(plan["briefs"]) == 1
    brief = plan["briefs"][0]
    assert brief["query"] == "best crm"
    assert brief["diagnosis"]["type"] == "content_gap"
    assert brief["competitors_winning"] == ["Globex"]
    assert brief["target_sources"] == [{"domain": "g2.com", "rivals": ["Globex"]}]
    assert "crm for startups" in brief["subtopics"]  # sibling query in same corpus
    assert any("best crm" in line for line in brief["outline"])
    assert plan["summary"]["content_gap"] == 1


def test_contestability_ranks_briefs_and_power_pages_group_by_url(db_session):
    from api.dashboards_service import citations_intel
    from api.models import QueryClassification

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="q hot", corpus_tag="crm"))
    db_session.add(Query(tenant_id=tid, text="q frozen", corpus_tag="crm"))
    db_session.commit()
    run1 = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    run2 = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run1)
    db_session.add(run2)
    db_session.commit()

    def rival(r):
        db_session.add(Mention(result_id=r.id, tenant_id=tid, entity_type="competitor",
                               entity_name="Globex", position=0, rank=1))
        db_session.commit()

    # "q hot": answer churns across runs (hash aaa -> bbb) and is search-driven.
    r1 = _result(db_session, run1.id, tid, "q hot", "openai_api", "search", rhash="aaa")
    rival(r1)
    r2 = _result(db_session, run2.id, tid, "q hot", "openai_api", "search", rhash="bbb")
    rival(r2)
    # Twin with no brand mention -> knowledge gap (brief-worthy).
    _result(db_session, run2.id, tid, "q hot", "openai_api", "nosearch")
    db_session.add(QueryClassification(tenant_id=tid, query_text="q hot",
                                       surface=SurfaceCode.openai_api,
                                       web_search_likelihood="very_likely"))

    # "q frozen": byte-identical answer across runs -> locked in.
    r3 = _result(db_session, run1.id, tid, "q frozen", "openai_api", "search", rhash="ccc")
    rival(r3)
    r4 = _result(db_session, run2.id, tid, "q frozen", "openai_api", "search", rhash="ccc")
    rival(r4)
    _result(db_session, run2.id, tid, "q frozen", "openai_api", "nosearch")

    # Citations: one URL feeds answers on BOTH queries; another feeds one.
    db_session.add(Citation(result_id=r2.id, tenant_id=tid,
                            url="https://g2.com/best-crm", domain="g2.com",
                            source_category="other"))
    db_session.add(Citation(result_id=r4.id, tenant_id=tid,
                            url="https://g2.com/best-crm", domain="g2.com",
                            source_category="other"))
    db_session.add(Citation(result_id=r2.id, tenant_id=tid,
                            url="https://blog.example.com/one-off", domain="blog.example.com",
                            source_category="other"))
    db_session.commit()

    plan = action_plan(db_session, tid)
    # Winnable-now first: churn 1.0 x dependence 1.0 = 100; frozen scores 0.
    assert [b["query"] for b in plan["briefs"]] == ["q hot", "q frozen"]
    hot, frozen = plan["briefs"]
    assert hot["contestability"]["score"] == 100
    assert hot["contestability"]["label"] == "winnable now"
    assert frozen["contestability"]["score"] == 0
    assert frozen["contestability"]["label"] == "locked in"
    assert plan["strike_zone"]["winnable now"] == 1
    assert plan["strike_zone"]["locked in"] == 1

    pages = citations_intel(db_session, tid)["power_pages"]
    # Breadth wins: the page feeding two queries ranks above the one-off.
    assert pages[0]["url"] == "https://g2.com/best-crm"
    assert pages[0]["queries"] == 2 and pages[0]["citations"] == 2
    assert pages[1]["queries"] == 1


def test_lost_citation_radar_diffs_brand_pages_across_runs(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="q1", corpus_tag="c"))
    db_session.add(Query(tenant_id=tid, text="q2", corpus_tag="c"))
    db_session.commit()
    run1 = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    run2 = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run1)
    db_session.add(run2)
    db_session.commit()

    def cite(run_id, qtext, url):
        r = _result(db_session, run_id, tid, qtext, "openai_api", "search")
        db_session.add(Citation(result_id=r.id, tenant_id=tid, url=url,
                                domain="acme.com", source_category="brand"))
        db_session.commit()

    # Run 1: /guide cited on q1+q2, /pricing on q1. Run 2: only /guide on q1.
    cite(run1.id, "q1", "https://acme.com/guide")
    cite(run1.id, "q2", "https://acme.com/guide")
    cite(run1.id, "q1", "https://acme.com/pricing")
    cite(run2.id, "q1", "https://acme.com/guide")

    protect = action_plan(db_session, tid)["protect"]
    assert protect["ready"] is True
    assert protect["held"] == 1 and protect["gained"] == 0
    lost = {entry["url"]: entry for entry in protect["lost"]}
    assert lost["https://acme.com/guide"]["queries"] == ["q2"]
    assert lost["https://acme.com/guide"]["still_cited_on"] == 1
    assert lost["https://acme.com/pricing"]["queries"] == ["q1"]
    assert lost["https://acme.com/pricing"]["still_cited_on"] == 0
