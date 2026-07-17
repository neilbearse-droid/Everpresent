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


def test_citability_diff_specs_winners_and_flags_your_gaps(db_session):
    from api.models import PagePresence

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="best crm", corpus_tag="crm"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()

    # Gap query: rival named, brand absent; twin knows brand -> content gap.
    s = _result(db_session, run.id, tid, "best crm", "openai_api", "search")
    db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                           entity_name="Globex", position=0, rank=1))
    ns = _result(db_session, run.id, tid, "best crm", "openai_api", "nosearch")
    db_session.add(Mention(result_id=ns.id, tenant_id=tid, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    # Cited on the query: two third-party winners and the brand's own page.
    for url, dom, cat in [("https://g2.com/best", "g2.com", "other"),
                          ("https://blog.example.com/top", "blog.example.com", "other"),
                          ("https://acme.com/crm", "acme.com", "brand")]:
        db_session.add(Citation(result_id=s.id, tenant_id=tid, url=url, domain=dom,
                                source_category=cat))
    db_session.commit()

    # Crawled fingerprints: winners carry the Tier-1 levers (capsule, stats,
    # quotations, cited sources) + tables; yours is thin and has none of them.
    winner_features = {"has_answer_capsule": True, "statistic_count": 12,
                       "quotation_count": 3, "citation_count": 6, "front_loaded": True,
                       "promotional_tone_score": 0.0, "json_ld": True, "faq_schema": True,
                       "has_tables": True, "recent_year_mentions": 8, "word_count": 2000}
    for url in ("https://g2.com/best", "https://blog.example.com/top"):
        db_session.add(PagePresence(tenant_id=tid, url=url, domain="x", status="ok",
                                    brand_found=False, features=dict(winner_features)))
    db_session.add(PagePresence(tenant_id=tid, url="https://acme.com/crm", domain="acme.com",
                                status="ok", brand_found=True,
                                features={"has_answer_capsule": False, "statistic_count": 1,
                                          "quotation_count": 0, "citation_count": 0,
                                          "front_loaded": False, "promotional_tone_score": 0.0,
                                          "json_ld": True, "faq_schema": False,
                                          "has_tables": False, "recent_year_mentions": 1,
                                          "word_count": 400}))
    db_session.commit()

    brief = action_plan(db_session, tid)["briefs"][0]
    cit = brief["citability"]
    assert cit["ready"] is True
    assert len(cit["winners"]) == 2
    # Spec captures both Tier-1 medians and hygiene.
    assert cit["spec"]["has_answer_capsule"] is True and cit["spec"]["statistic_count"] == 12
    assert cit["spec"]["word_count"] == 2000
    assert cit["your_page"]["url"] == "https://acme.com/crm"
    gaps = " | ".join(cit["gaps"])
    # Tier-1 levers lead the gap list.
    assert "answer capsule" in gaps
    assert "statistics/data points" in gaps
    assert "quotations" in gaps
    assert "comparison tables" in gaps  # hygiene still flagged, but later
    assert "too thin" in gaps
    # Tier-1 gaps come before hygiene gaps.
    assert cit["gaps"].index(next(g for g in cit["gaps"] if "answer capsule" in g)) < \
        cit["gaps"].index(next(g for g in cit["gaps"] if "comparison tables" in g))


def test_citability_handles_no_owned_page_and_uncrawled_winners(db_session):
    from api.models import PagePresence

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="q a", corpus_tag="c"))
    db_session.add(Query(tenant_id=tid, text="q b", corpus_tag="c"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()

    for q in ("q a", "q b"):
        s = _result(db_session, run.id, tid, q, "openai_api", "search")
        db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                               entity_name="Globex", position=0, rank=1))
        _result(db_session, run.id, tid, q, "openai_api", "nosearch")
        db_session.add(Citation(result_id=s.id, tenant_id=tid,
                                url=f"https://site.example/{q.replace(' ', '')}",
                                domain="site.example", source_category="other"))
    db_session.commit()
    # Only q a's winner has been crawled; no brand page anywhere.
    db_session.add(PagePresence(tenant_id=tid, url="https://site.example/qa", domain="x",
                                status="ok", brand_found=False,
                                features={"json_ld": False, "faq_schema": False,
                                          "has_tables": False, "recent_year_mentions": 0,
                                          "word_count": 900}))
    db_session.commit()

    briefs = {b["query"]: b for b in action_plan(db_session, tid)["briefs"]}
    assert briefs["q a"]["citability"]["ready"] is True
    assert briefs["q a"]["citability"]["your_page"] is None
    assert any("build one" in g for g in briefs["q a"]["citability"]["gaps"])
    assert briefs["q b"]["citability"]["ready"] is False  # winners not crawled yet
