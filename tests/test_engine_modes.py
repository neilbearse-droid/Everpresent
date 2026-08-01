"""Reframed Overview: 'AI visibility' is not one number. engine_modes() bands
each surface retrieve-vs-recall by observed search propensity and reports the
brand's standing in the currency that fits that mode."""

from api.dashboards_service import engine_modes
from api.models import (
    BrandProfile,
    Citation,
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
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.add(Competitor(tenant_id=t.id, name="Rival", aliases=[], domains=["rival.com"]))
    db.add(Query(tenant_id=t.id, text="best crm", branded=False))
    db.add(Query(tenant_id=t.id, text="Acme review", branded=True))
    db.commit()
    return t.id


def _run(db, tid):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _result(db, tid, run, qtext, surface, variant, *, searched=0, fanout=None,
            brand=False, cited=False):
    r = Result(
        run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
        persona_segment="seg", surface=surface, variant=variant,
        status=ResultStatus.ok, web_search_calls=searched,
        fanout_queries=fanout or [],
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    if brand:
        db.add(Mention(result_id=r.id, tenant_id=tid, entity_type="brand",
                       entity_name="Acme", position=0, rank=1, sentiment="neutral",
                       context_snippet="Acme."))
    if cited:
        db.add(Citation(result_id=r.id, tenant_id=tid, url="https://acme.com/x",
                        domain="acme.com", source_category="brand"))
    db.commit()
    return r


def _by_surface(report):
    return {e["surface"]: e for e in report["engines"]}


def test_gemini_retrieves_chatgpt_recalls(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)

    # Gemini (gemini_api): searches on every prompt, fans out — RETRIEVE.
    # (query_text is a snapshot on the result; only branded texts are excluded,
    # so extra competitive prompts need no Query row.)
    for i, q in enumerate(["best crm", "top crm tools", "crm for smb"]):
        _result(db_session, tid, run, q, SurfaceCode.gemini_api, ResultVariant.search,
                searched=3, fanout=["a", "b", "c"], brand=(i == 0), cited=(i == 0))

    # ChatGPT (openai_api) is FORCED — its natural probe is the routing signal.
    # Natural answers come from memory (no search) and name the brand — RECALL.
    for q in ["best crm", "top crm tools", "crm for smb"]:
        _result(db_session, tid, run, q, SurfaceCode.openai_api, ResultVariant.search,
                searched=1, fanout=["x"], brand=True, cited=True)
        _result(db_session, tid, run, q, SurfaceCode.openai_api, ResultVariant.natural,
                searched=0, brand=True)

    rep = engine_modes(db_session, tid)
    eng = _by_surface(rep)

    assert eng["gemini_api"]["mode"] == "retrieve"
    assert eng["gemini_api"]["standing_unit"] == "cited"
    assert eng["gemini_api"]["avg_fanout"] == 3.0
    assert eng["gemini_api"]["search_rate"] == 100.0

    # ChatGPT reads from its natural probe: 0/3 searched -> recall, standing is
    # named-from-memory (brand named in all 3 natural answers).
    assert eng["openai_api"]["mode"] == "recall"
    assert eng["openai_api"]["from_probe"] is True
    assert eng["openai_api"]["search_rate"] == 0.0
    assert eng["openai_api"]["standing_unit"] == "named"
    assert eng["openai_api"]["standing_value"] == 100.0


def test_mixed_band(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)
    # perplexity_api: searches on 2 of 4 -> 50% -> mixed.
    for i in range(4):
        q = f"q{i}"
        db_session.add(Query(tenant_id=tid, text=q, branded=False))
        db_session.commit()
        _result(db_session, tid, run, q, SurfaceCode.perplexity_api,
                ResultVariant.search, searched=1 if i < 2 else 0, brand=(i == 0))
    rep = engine_modes(db_session, tid)
    assert _by_surface(rep)["perplexity_api"]["mode"] == "mixed"


def test_two_mode_split_and_branded_excluded(db_session):
    tid = _tenant(db_session)
    run = _run(db_session, tid)

    # Competitive: one searched answer naming brand (retrieval hit), one training
    # twin naming brand (recall hit).
    _result(db_session, tid, run, "best crm", SurfaceCode.gemini_api,
            ResultVariant.search, searched=2, brand=True)
    _result(db_session, tid, run, "best crm", SurfaceCode.openai_api,
            ResultVariant.nosearch, searched=0, brand=True)

    # Branded query must NOT count in either mode's visibility.
    _result(db_session, tid, run, "Acme review", SurfaceCode.gemini_api,
            ResultVariant.search, searched=2, brand=True)
    _result(db_session, tid, run, "Acme review", SurfaceCode.openai_api,
            ResultVariant.nosearch, searched=0, brand=True)

    rep = engine_modes(db_session, tid)
    # 1 training twin, brand named -> recall 100% over 1 answer.
    assert rep["modes"]["recall"] == {"visibility": 100.0, "answers": 1}
    # 1 searched answer, brand named -> retrieval 100% over 1 answer.
    assert rep["modes"]["retrieval"] == {"visibility": 100.0, "answers": 1}


def test_empty_tenant_observed_false(db_session):
    tid = _tenant(db_session)
    rep = engine_modes(db_session, tid)
    assert rep["observed"] is False
    assert rep["engines"] == []
    assert rep["composite"] is None
