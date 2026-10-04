"""Future-proofing builds (m33): answer shape and model timeline, memory vs
search, themes/objections, own-page audit, first-party imports."""

from datetime import timedelta

from sqlmodel import select

from api.models import (
    BrandProfile,
    Citation,
    FirstPartyDaily,
    Mention,
    PagePresence,
    Recommendation,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    User,
    utcnow,
)
from engine.processing.answer_shape import link_kind


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme", clerk_org_id="org_a")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def _result(db, tid, *, surface=SurfaceCode.openai_api, variant=ResultVariant.search,
            model="", days_ago=1, searches=1, query="best crm"):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    r = Result(run_id=run.id, tenant_id=tid, query_text=query, persona_name="p",
               surface=surface, variant=variant, status=ResultStatus.ok,
               served_model=model, web_search_calls=searches,
               created_at=utcnow() - timedelta(days=days_ago))
    db.add(r)
    db.commit()
    return r


def _mention(db, r, snippet="Acme is a solid pick."):
    db.add(Mention(result_id=r.id, tenant_id=r.tenant_id, entity_type="brand",
                   entity_name="Acme", position=0, rank=1, context_snippet=snippet))
    db.commit()


def test_link_kind_separates_inline_links_from_source_markers():
    assert link_kind("Acme", "https://acme.com/") == "inline"  # brand name → homepage
    assert link_kind("acme", "https://acme.com/pricing") == "source"  # site chip → page
    assert link_kind("try Acme Websites", "https://acme.com/websites") == "inline"
    for marker in ("", "1", "[2]", "(3)", "+4", "acme.com", "www.acme.com", "acme",
                   "techradar.com", "PCM"):
        assert link_kind(marker, "https://acme.com/x") == "source", marker


def test_answer_shape_per_model_and_timeline(db_session):
    from api.answer_shape_service import answer_shape, model_timeline

    t = _tenant(db_session)
    for i, model in enumerate(["gpt-5.6", "gpt-5.6", "gpt-6-astra", "gpt-6-astra"]):
        r = _result(db_session, t.id, model=model, days_ago=10 - i)
        _mention(db_session, r)
        kinds = [("brand", "inline"), ("other", "source")] if model == "gpt-6-astra" else \
            [("other", "source"), ("other", "source"), ("competitor", "source")]
        for cat, kind in kinds:
            db_session.add(Citation(result_id=r.id, tenant_id=t.id, url="https://x.test/a",
                                    domain="x.test", source_category=cat, link_kind=kind))
    db_session.commit()
    rep = answer_shape(db_session, t.id)
    by_model = {e["model"]: e for e in rep["engines"]}
    assert by_model["gpt-5.6"]["citations_per_answer"] == 3.0
    assert by_model["gpt-6-astra"]["own_share"] == 50.0
    assert by_model["gpt-6-astra"]["inline_share"] == 50.0
    assert by_model["gpt-5.6"]["mentioned_unlinked_share"] == 100.0
    [change] = model_timeline(db_session, t.id)
    assert change["model"] == "gpt-6-astra" and rep["model_changes"] == [change]


def test_memory_vs_search_and_objections(db_session):
    from api.answer_shape_service import answer_shape

    t = _tenant(db_session)
    for _i in range(12):  # known from memory every time
        r = _result(db_session, t.id, variant=ResultVariant.nosearch, searches=0)
        _mention(db_session, r, "Acme is cheap at first, but renewal prices jump a lot.")
    for i in range(12):  # with search only a third name it
        r = _result(db_session, t.id)
        if i % 3 == 0:
            _mention(db_session, r, "Acme has easy templates and 24/7 support.")
    rep = answer_shape(db_session, t.id)
    [row] = rep["memory_vs_search"]
    assert row["verdict"] == "known, but losing in search"
    themes = {th["theme"]: th for th in rep["perception"]["themes"]}
    assert themes["Renewals"]["objections"] == 12 and themes["Renewals"]["memory"] == 12
    assert themes["Support"]["objections"] == 0
    assert rep["perception"]["themes"][0]["theme"] in ("Price", "Renewals")


def test_own_pages_flags_conflicts_staleness_and_unsampled(db_session):
    from api.own_pages_service import own_pages

    t = _tenant(db_session)
    r = _result(db_session, t.id)
    for url in ("https://www.acme.com/pricing/", "https://acme.com/help/renew",
                "https://rival.com/x"):
        db_session.add(Citation(result_id=r.id, tenant_id=t.id, url=url,
                                domain=url.split("/")[2], link_kind="inline"))
    db_session.add(PagePresence(
        tenant_id=t.id, url="https://acme.com/pricing", domain="acme.com", status="ok",
        features={"has_updated_date": True, "latest_year": utcnow().year,
                  "fact_conflicts": [{"fact_id": 1, "subject": "starter price",
                                      "expected": "$9.99", "stated": "$12.99",
                                      "snippet": "Starter is $12.99"}]}))
    db_session.add(PagePresence(
        tenant_id=t.id, url="https://acme.com/help/renew", domain="acme.com", status="ok",
        features={"has_updated_date": False, "latest_year": 2023}))
    db_session.add(FirstPartyDaily(tenant_id=t.id, source="gsc", date="2026-10-01",
                                   page="/domains", metric="impressions", value=500))
    db_session.commit()
    rep = own_pages(db_session, t.id)
    pages = {p["path"]: p for p in rep["pages"]}
    assert set(pages) == {"/pricing", "/help/renew"}  # rival page excluded, www merged
    assert pages["/pricing"]["flags"] == ["facts conflict"]
    assert "stale" in pages["/help/renew"]["flags"]
    assert rep["pages"][0]["path"] == "/pricing"  # worst first
    assert rep["in_ai_features_not_sampled"][0]["path"] == "/domains"


def test_own_page_and_model_change_plays(db_session):
    from api.recommendations_service import generate_recommendations

    t = _tenant(db_session)
    r = _result(db_session, t.id, model="gpt-5.6", days_ago=5)
    _result(db_session, t.id, model="gpt-6-astra", days_ago=2)
    db_session.add(Citation(result_id=r.id, tenant_id=t.id, url="https://acme.com/pricing",
                            domain="acme.com"))
    db_session.add(PagePresence(
        tenant_id=t.id, url="https://acme.com/pricing", domain="acme.com", status="ok",
        features={"fact_conflicts": [{"fact_id": 1, "subject": "price", "expected": "$9",
                                      "stated": "$12", "snippet": ""}]}))
    db_session.commit()
    generate_recommendations(db_session, t)
    refs = {x.gap_ref for x in db_session.exec(select(Recommendation)).all()}
    assert "own_page:facts:/pricing" in refs
    assert "model_change:openai_api:gpt-6-astra" in refs


def test_crawl_fact_conflicts_on_own_pages():
    from engine.processing.accuracy import FactSpec
    from worker.page_crawl import _fact_conflicts

    facts = [FactSpec(id=1, category="pricing", label="Starter price", subject="starter plan",
                      aliases=[], kind="numeric", expected="$9.99")]
    html = ("<script>var p='The starter plan costs $1';</script>"
            "<p>The starter plan costs $14.99 per month.</p>")
    [c] = _fact_conflicts(html, facts)
    assert c["stated"] == "$14.99" and c["expected"] == "$9.99"
    assert _fact_conflicts("<p>The starter plan costs $9.99 per month.</p>", facts) == []


GSC = """Generative AI performance export
Date,Page,Impressions
2026-09-30,https://acme.com/pricing,120
2026-10-01,https://acme.com/pricing/,80
2026-10-01,https://acme.com/domains,"1,500"
Total,,1700
"""

BING = "Cited URL\tCitations\tGrounding query\nhttps://acme.com/help\t42\tbest registrar\n"


def test_first_party_import_maps_columns_and_replaces(client, login, db_session):
    _tenant(db_session)
    u = User(email="m@x.test", clerk_user_id="u_m")
    db_session.add(u)
    db_session.commit()
    login(u, org_id="org_a", org_role="org:admin")
    res = client.post("/api/tenant/first-party?source=gsc", content=GSC.encode())
    assert res.status_code == 200, res.text
    assert res.json()["metrics"] == ["impressions"] and res.json()["pages"] == 2
    again = client.post("/api/tenant/first-party?source=gsc", content=GSC.encode())
    assert again.status_code == 200
    rows = db_session.exec(select(FirstPartyDaily).where(
        FirstPartyDaily.page == "/domains")).all()
    assert [r.value for r in rows] == [1500.0]  # replaced, not doubled
    assert client.post("/api/tenant/first-party?source=bing",
                       content=BING.encode()).json()["metrics"] == ["citations"]
    summary = client.get("/api/tenant/first-party").json()["sources"]
    assert {(s["source"], s["metric"], s["total"]) for s in summary} == {
        ("gsc", "impressions", 1700.0), ("bing", "citations", 42.0)}
    bad = client.post("/api/tenant/first-party?source=nope", content=b"a,b\n1,2")
    assert bad.status_code == 400
    assert client.post("/api/tenant/first-party?source=gsc", content=b"a,b\nx,y").status_code == 400
    assert client.delete("/api/tenant/first-party?source=bing").json()["deleted"] == 1
    assert client.get("/api/tenant/answer-shape").status_code == 200
    assert client.get("/api/tenant/own-pages").status_code == 200


def test_objections_only_count_sentences_naming_the_brand(db_session):
    from api.answer_shape_service import answer_shape

    t = _tenant(db_session)
    r = _result(db_session, t.id)
    _mention(db_session, r, "Rivalco has strong templates but support can be slow. "
                            "Acme has strong templates and fast support.")
    themes = {th["theme"]: th for th in answer_shape(db_session, t.id)["perception"]["themes"]}
    assert themes["Support"]["mentions"] == 1 and themes["Support"]["objections"] == 0


def test_checker_blocked_but_bots_read_is_not_unreachable(db_session):
    from api.agent_analytics import ingest_lines
    from api.own_pages_service import own_pages

    t = _tenant(db_session)
    r = _result(db_session, t.id)
    db_session.add(Citation(result_id=r.id, tenant_id=t.id, url="https://acme.com/",
                            domain="acme.com"))
    db_session.add(PagePresence(tenant_id=t.id, url="https://acme.com/", domain="acme.com",
                                status="error", http_status=403, features={}))
    db_session.commit()
    ts = utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")
    ingest_lines(db_session, t.id, [f'1.1.1.1 - - [{ts}] "GET / HTTP/1.1" 200 1 "-" '
                                    '"OAI-SearchBot/1.0"'] * 5, verify=False)
    db_session.commit()
    rep = own_pages(db_session, t.id)
    assert rep["pages"][0]["flags"] == ["blocks our checker"] and rep["flagged"] == 0
