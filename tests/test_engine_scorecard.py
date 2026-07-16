"""Cross-engine scorecard + 'why you're missing' diagnosis, over hand-built
results so each diagnosis branch is exercised deterministically."""

from api.dashboards_service import engine_scorecard
from api.models import (
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)


def _run(db, tenant_id) -> int:
    run = Run(tenant_id=tenant_id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    assert run.id is not None
    return run.id


def _result(db, run_id, tid, qtext, surface, variant) -> Result:
    r = Result(
        run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
        surface=SurfaceCode(surface), variant=ResultVariant(variant), status=ResultStatus.ok,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _mention(db, result_id, tid, entity_type, name):
    db.add(Mention(result_id=result_id, tenant_id=tid, entity_type=entity_type,
                   entity_name=name, position=0, rank=1))
    db.commit()


def _brand(db, r, tid):
    _mention(db, r.id, tid, "brand", "Acme")


def _rival(db, r, tid, name="Globex"):
    _mention(db, r.id, tid, "competitor", name)


def test_scorecard_and_all_diagnosis_branches(db_session):
    from api.models import Query

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    for text in ("q visible", "q content", "q knowledge"):
        db_session.add(Query(tenant_id=tid, text=text))
    db_session.commit()
    run_id = _run(db_session, tid)

    # q visible: brand appears in a live-search answer on openai; claude shows a rival.
    r = _result(db_session, run_id, tid, "q visible", "openai_api", "search")
    _brand(db_session, r, tid)
    r2 = _result(db_session, run_id, tid, "q visible", "claude_api", "search")
    _rival(db_session, r2, tid)

    # q content: absent when searching, but the training-only twin knows the brand
    # -> content gap.
    r = _result(db_session, run_id, tid, "q content", "openai_api", "search")
    _rival(db_session, r, tid)
    ns = _result(db_session, run_id, tid, "q content", "openai_api", "nosearch")
    _brand(db_session, ns, tid)

    # q knowledge: absent in search AND in the training twin -> knowledge gap.
    r = _result(db_session, run_id, tid, "q knowledge", "openai_api", "search")
    _rival(db_session, r, tid)
    _result(db_session, run_id, tid, "q knowledge", "openai_api", "nosearch")  # no brand mention

    card = engine_scorecard(db_session, tid)

    assert card["brand_name"] == "Acme"
    assert card["diagnosis_summary"] == {"visible": 1, "content_gap": 1, "knowledge_gap": 1}

    by_query = {m["query"]: m for m in card["matrix"]}
    assert by_query["q visible"]["diagnosis"]["type"] == "visible"
    assert by_query["q visible"]["cells"]["openai_api"]["state"] == "brand"
    assert by_query["q visible"]["cells"]["claude_api"]["state"] == "competitor"
    assert by_query["q content"]["diagnosis"]["type"] == "content_gap"
    assert by_query["q knowledge"]["diagnosis"]["type"] == "knowledge_gap"

    engines = {e["surface"]: e for e in card["engines"]}
    assert engines["openai_api"]["queries_measured"] == 3
    assert engines["openai_api"]["brand_present"] == 1  # only "q visible"
    assert engines["openai_api"]["brand_rate"] == round(100 / 3, 1)
    assert engines["claude_api"]["top_competitor"] == "Globex"


def test_undetermined_when_no_training_baseline(db_session):
    from api.models import Query

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(Query(tenant_id=tid, text="q"))
    db_session.commit()
    run_id = _run(db_session, tid)

    # Perplexity only (no nosearch twin), brand absent -> cause can't be determined.
    r = _result(db_session, run_id, tid, "q", "perplexity_api", "search")
    _rival(db_session, r, tid)

    card = engine_scorecard(db_session, tid)
    assert card["diagnosis_summary"] == {"undetermined": 1}
    assert card["matrix"][0]["diagnosis"]["type"] == "undetermined"
