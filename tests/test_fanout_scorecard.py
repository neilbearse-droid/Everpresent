"""Fan-out MAP (free tier): the shards engines issued per prompt, indicative
shard-text signals (names brand / competitor), and real prompt-level presence.
Per-shard *presence* is intentionally not claimed here — that's the re-probe
phase. Branded prompts are excluded."""

from api.dashboards_service import fanout_scorecard
from api.models import (
    BrandProfile,
    Competitor,
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


def _tenant(db):
    t = Tenant(name="GoDaddy", slug="godaddy")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="GoDaddy", aliases=[], domains=["godaddy.com"]))
    db.add(Competitor(tenant_id=t.id, name="Namecheap", aliases=["NC"], domains=["namecheap.com"]))
    db.add(Query(tenant_id=t.id, text="best domain registrar", branded=False))
    db.add(Query(tenant_id=t.id, text="GoDaddy review", branded=True))
    db.commit()
    return t.id


def _run(db, tid):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _result(db, tid, run, qtext, surface, *, fanout, brand=False):
    r = Result(
        run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
        persona_segment="seg", surface=surface, variant=ResultVariant.search,
        status=ResultStatus.ok, web_search_calls=len(fanout), fanout_queries=fanout,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    if brand:
        db.add(Mention(result_id=r.id, tenant_id=tid, entity_type="brand",
                       entity_name="GoDaddy", position=0, rank=1, sentiment="neutral",
                       context_snippet="GoDaddy."))
    db.commit()
    return r


def test_map_shards_reach_and_indicative_signals(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)
    # Gemini issues 3 shards; ChatGPT issues 2 (one overlapping). Brand appears
    # in the Gemini answer, not the ChatGPT one.
    _result(db_session, tid, run, "best domain registrar", SurfaceCode.gemini_api,
            fanout=["cheapest domain registrar", "GoDaddy vs Namecheap",
                    "registrar with free privacy"],
            brand=True)
    _result(db_session, tid, run, "best domain registrar", SurfaceCode.openai_api,
            fanout=["cheapest domain registrar", "best registrar for small business"],
            brand=False)

    rep = fanout_scorecard(db_session, tid)
    assert rep["observed"] is True
    assert rep["branded_excluded"] is True
    assert len(rep["prompts"]) == 1
    p = rep["prompts"][0]

    # Union of shards across engines (one shared) -> 4 distinct.
    assert p["shards_total"] == 4
    assert p["engines_count"] == 2
    assert p["reach_by_engine"] == {"ChatGPT": 2, "Gemini": 3}
    # Brand appeared in at least one final answer.
    assert p["brand_in_answer"] is True

    by_text = {s["text"]: s for s in p["shards"]}
    # Shared shard issued by both engines, sorted -> two labels.
    assert by_text["cheapest domain registrar"]["engines"] == ["ChatGPT", "Gemini"]
    # Indicative shard-text signals.
    assert by_text["GoDaddy vs Namecheap"]["names_brand"] is True
    assert by_text["GoDaddy vs Namecheap"]["names_competitors"] == ["Namecheap"]
    assert by_text["cheapest domain registrar"]["names_brand"] is False
    assert by_text["cheapest domain registrar"]["names_competitors"] == []
    # One shard explicitly names a competitor -> contested count.
    assert p["contested"] == 1


def test_branded_prompt_excluded(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)
    _result(db_session, tid, run, "GoDaddy review", SurfaceCode.gemini_api,
            fanout=["is GoDaddy good", "GoDaddy complaints"], brand=True)
    rep = fanout_scorecard(db_session, tid)
    assert rep["observed"] is False
    assert rep["prompts"] == []


def test_word_boundary_no_false_substring(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)
    # "namecheapish" must NOT match the competitor token "namecheap".
    _result(db_session, tid, run, "best domain registrar", SurfaceCode.gemini_api,
            fanout=["namecheapish alternatives"], brand=False)
    rep = fanout_scorecard(db_session, tid)
    shard = rep["prompts"][0]["shards"][0]
    assert shard["names_competitors"] == []
