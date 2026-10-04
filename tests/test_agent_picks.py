"""Agent picks: first-pick rate on task and coding prompts."""

from api.models import (
    BrandProfile,
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

TASK = "Register a domain for my bakery"
CODE = "Write a script that registers a domain"


def _answer(db, t, run, surface, text, picks):
    r = Result(run_id=run.id, tenant_id=t.id, query_text=text, persona_name="generic",
               surface=surface, variant=ResultVariant.search, status=ResultStatus.ok)
    db.add(r)
    db.commit()
    for rank, (etype, name) in enumerate(picks, start=1):
        db.add(Mention(result_id=r.id, tenant_id=t.id, entity_type=etype, entity_name=name,
                       position=rank * 10, rank=rank))
    db.commit()


def _setup(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme"))
    db.add_all([Query(tenant_id=t.id, text=TASK, corpus_tag="agent_task"),
                Query(tenant_id=t.id, text=CODE, corpus_tag="agent_code"),
                Query(tenant_id=t.id, text="best registrar?", corpus_tag="domains")])
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return t, run


def test_no_agent_prompts(db_session):
    from api.agent_picks_service import agent_picks

    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    d = agent_picks(db_session, t.id)
    assert d["has_prompts"] is False and d["has_data"] is False


def test_first_pick_rates(db_session):
    from api.agent_picks_service import agent_picks

    t, run = _setup(db_session)
    brand, rival = ("brand", "Acme"), ("competitor", "Rival")
    for _ in range(3):
        _answer(db_session, t, run, SurfaceCode.openai_api, TASK, [rival, brand])
    _answer(db_session, t, run, SurfaceCode.openai_api, TASK, [brand])
    _answer(db_session, t, run, SurfaceCode.claude_api, CODE, [])
    _answer(db_session, t, run, SurfaceCode.claude_api, CODE, [brand, rival])
    # A plain question never counts as an agent prompt.
    _answer(db_session, t, run, SurfaceCode.openai_api, "best registrar?", [brand])
    d = agent_picks(db_session, t.id)
    o = d["overall"]
    assert o["first_pick"]["answers"] == 6 and o["first_pick"]["mentioned"] == 2
    assert o["named"]["mentioned"] == 5
    assert o["top_rival"] == {"name": "Rival", "rate": 50.0}
    assert o["no_pick"] == round(100 / 6, 1)
    eng = {e["surface"]: e for e in d["engines"]}
    assert eng["openai_api"]["first_pick"]["rate"] == 25.0
    assert eng["openai_api"]["leader"] == "Rival"
    assert {k["kind"] for k in d["kinds"]} == {"Task", "Coding"}
    assert d["prompts"][0]["text"] == TASK  # weakest first


def test_briefing_flags_a_rival_picked_first(db_session):
    from api.briefing_service import briefing

    t, run = _setup(db_session)
    for _ in range(12):
        _answer(db_session, t, run, SurfaceCode.openai_api, TASK,
                [("competitor", "Rival"), ("brand", "Acme")])
    reasons = briefing(db_session, t.id)["why"]
    assert any(r["kind"] == "agent_pick" and "Rival" in r["text"] for r in reasons)
