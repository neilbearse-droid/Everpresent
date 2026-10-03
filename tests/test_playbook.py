"""The recommendations playbook: each signal becomes a specific, ranked,
evidence-graded play, and regeneration keeps human statuses while refreshing
the text."""

from sqlmodel import select

from api.agent_analytics import ingest_lines
from api.models import (
    AccuracyFinding,
    BrandProfile,
    Citation,
    FanoutShard,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.recommendations_service import (
    _accuracy_plays,
    _agent_plays,
    _refresh_plays,
    _source_plays,
    _subquery_plays,
    generate_recommendations,
)

TS = utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def _line(path: str, status: int, ua: str) -> str:
    return f'1.1.1.1 - - [{TS}] "GET {path} HTTP/1.1" {status} 10 "-" "{ua}"'


def test_no_logs_gives_one_setup_play(db_session):
    t = _tenant(db_session)
    plays = _agent_plays(db_session, t.id)
    assert [p.branch for p in plays] == ["connect_logs"]


def test_missing_and_erroring_search_bots_become_crawler_plays(db_session):
    t = _tenant(db_session)
    lines = (
        [_line("/", 200, "OAI-SearchBot/1.0")] * 150
        + [_line("/", 403, "PerplexityBot/1.0")] * 60
        + [_line("/gone", 404, "Googlebot/2.1")] * 30
        + [_line("/", 200, "bingbot/2.0")] * 30
        + [_line("/", 200, "Claude-SearchBot/1.0")] * 10
    )
    ingest_lines(db_session, t.id, lines, verify=False)
    db_session.commit()
    by_ref = {p.gap_ref: p for p in _agent_plays(db_session, t.id)}
    assert "crawler:PerplexityBot:errors" in by_ref  # 100% errors
    assert by_ref["crawler:PerplexityBot:errors"].priority >= 88
    assert not any(r.startswith("crawler:OAI-SearchBot") for r in by_ref)
    assert "/gone" in by_ref["broken_pages"].action_text
    assert all(p.evidence and p.why and p.steps for p in by_ref.values())


def test_too_few_hits_never_claims_a_bot_is_missing(db_session):
    t = _tenant(db_session)
    ingest_lines(db_session, t.id, [_line("/", 200, "GPTBot/1.2")] * 20, verify=False)
    db_session.commit()
    assert not any(p.branch == "crawler_access" for p in _agent_plays(db_session, t.id))


def test_source_plays_group_targets_by_kind():
    plan = {"targets": [
        {"domain": "g2.com", "competitor_assoc": 3, "brand_assoc": 0},
        {"domain": "trustpilot.com", "competitor_assoc": 5, "brand_assoc": 2},
        {"domain": "techradar.com", "competitor_assoc": 2, "brand_assoc": 0},
        {"domain": "reddit.com", "competitor_assoc": 18, "brand_assoc": 4},
        {"domain": "en.wikipedia.org", "competitor_assoc": 2, "brand_assoc": 1},
        {"domain": "pcmag.com", "competitor_assoc": 4, "brand_assoc": 3},  # cites you too
        {"domain": "nobody.example", "competitor_assoc": 1, "brand_assoc": 0},  # too few
    ]}
    plays = {p.branch: p for p in _source_plays(plan)}
    assert set(plays) == {"reviews", "earned", "community", "reference"}
    assert "g2.com" in plays["reviews"].title and "trustpilot.com" in plays["reviews"].title
    assert "techradar.com" in plays["earned"].title
    assert "pcmag.com" not in plays["earned"].action_text  # cites you nearly as often
    assert "ChatGPT" in plays["community"].action_text  # engine-specific advice
    assert plays["reviews"].priority > plays["community"].priority


def test_refresh_play_per_lost_citation():
    plan = {"protect": {"lost": [{"url": "https://acme.com/pricing",
                                  "queries": ["cheap crm", "crm pricing"]}]}}
    [p] = _refresh_plays(plan)
    assert p.gap_ref == "refresh:https://acme.com/pricing"
    assert "“cheap crm”" in p.action_text and p.priority == 80


def _run(db, tid) -> Run:
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return run


def test_subquery_plays_group_by_query(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    for text, reach, present, winners in (
        ("crm pricing 2026", 3, False, ["Globex"]),
        ("crm for startups", 1, False, []),
        ("acme crm review", 2, True, []),
    ):
        db_session.add(FanoutShard(tenant_id=t.id, run_id=run.id, parent_query_text="best crm",
                                   shard_text=text, shard_norm=text, reach=reach,
                                   brand_present=present, winners=winners,
                                   source="reprobed"))
    db_session.commit()
    [p] = _subquery_plays(db_session, t.id)  # grouped per parent query
    assert p.title == "Cover the sub-questions behind “best crm”"
    # Highest reach first; the shard the brand already wins is left out.
    assert p.action_text.index("crm pricing 2026") < p.action_text.index("crm for startups")
    assert "acme crm review" not in p.action_text
    assert "Globex appears" in p.action_text and p.priority == 78


def test_accuracy_play_names_the_sources_to_fix(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    r = Result(run_id=run.id, tenant_id=t.id, query_text="acme price", persona_name="p",
               surface=SurfaceCode.openai_api, variant=ResultVariant.search,
               status=ResultStatus.ok)
    db_session.add(r)
    db_session.commit()
    db_session.add(AccuracyFinding(result_id=r.id, tenant_id=t.id, fact_id=7,
                                   subject="starter price", expected="$9.99", stated="$19.99"))
    db_session.add(Citation(result_id=r.id, tenant_id=t.id,
                            url="https://oldreview.example/acme", domain="oldreview.example"))
    db_session.commit()
    [p] = _accuracy_plays(db_session, t.id)
    assert p.branch == "accuracy" and p.priority >= 94
    assert "$19.99" in p.action_text and "$9.99" in p.action_text
    assert any("oldreview.example/acme" in s for s in p.steps)


def test_regeneration_keeps_status_and_refreshes_text(db_session):
    t = _tenant(db_session)
    generate_recommendations(db_session, t)
    rec = db_session.exec(select(Recommendation)).one()  # the connect-logs play
    rec.status = RecommendationStatus.in_progress
    rec.action_text = "stale"
    db_session.add(rec)
    db_session.commit()
    generate_recommendations(db_session, t)
    db_session.expire_all()
    rec = db_session.exec(select(Recommendation)).one()
    assert rec.status == RecommendationStatus.in_progress
    assert rec.action_text != "stale" and rec.title and rec.why


def test_query_gap_when_named_on_a_minority_of_engines(db_session):
    from api.models import Mention, Query, QueryClassification
    from api.recommendations_service import _query_plays

    t = _tenant(db_session)
    run = _run(db_session, t.id)
    db_session.add(Query(tenant_id=t.id, text="best crm"))
    db_session.add(QueryClassification(tenant_id=t.id, query_text="best crm",
                                       surface=SurfaceCode.openai_api,
                                       web_search_likelihood="likely"))
    surfaces = [SurfaceCode.openai_api, SurfaceCode.claude_api, SurfaceCode.gemini_api,
                SurfaceCode.perplexity_api]
    for i, sc in enumerate(surfaces):
        r = Result(run_id=run.id, tenant_id=t.id, query_text="best crm", persona_name="p",
                   surface=sc, variant=ResultVariant.search, status=ResultStatus.ok)
        db_session.add(r)
        db_session.commit()
        name, etype = ("Acme", "brand") if i == 0 else ("Globex", "competitor")
        db_session.add(Mention(result_id=r.id, tenant_id=t.id, entity_type=etype,
                               entity_name=name, position=0, rank=1))
    db_session.commit()
    [p] = _query_plays(db_session, t.id, {})
    assert p.branch == "web_search" and "Globex" in p.action_text
    assert "named on ChatGPT but missing on" in p.action_text
    assert "Perplexity" in p.action_text
