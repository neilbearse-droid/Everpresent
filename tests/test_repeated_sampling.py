"""Repeated sampling: generic cells get N samples per run (plan-set), rotating
through the query's paraphrases; persona cells stay at one sample; every
sample is recorded under the canonical question."""

from sqlmodel import select

from api.models import Persona, Query, Result, ResultVariant, Run, RunStatus, Tenant
from engine.retrievers.openai_api import RetrievalOutcome, parse_responses_payload
from tests.test_runs import FIXTURE, _pending_run, job_env, make_tenant  # noqa: F401


def _setup(db_session, plan: str) -> Tenant:
    t = make_tenant(db_session, queries=0, personas=0)
    t.plan = plan
    db_session.add(t)
    db_session.add(Persona(tenant_id=t.id, name="Generic", prompt_text="",
                           segment_tag="generic"))
    db_session.add(Persona(tenant_id=t.id, name="Founder", prompt_text="You are a founder.",
                           segment_tag="founder"))
    db_session.add(Query(tenant_id=t.id, text="best crm",
                         paraphrases=["which crm should I pick", "top crm tools"],
                         persona_runs=[{"segment": "founder"}]))
    db_session.commit()
    return t


def test_generic_cells_are_sampled_n_times_with_rotating_wordings(
    db_session, job_env, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_a

    asked: list[tuple[str, str]] = []

    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s,
                    web_search=True, force_search=True):
        if web_search and force_search:
            asked.append((persona_prompt, query_text))
        return RetrievalOutcome(payload=FIXTURE, parsed=parse_responses_payload(FIXTURE),
                                latency_ms=1)

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)
    t = _setup(db_session, "command")  # samples_per_cell = 3
    run_id = _pending_run(db_session, t)
    run_mode_a(run_id)

    generic = sorted(q for (p, q) in asked if p == "")
    founder = [q for (p, q) in asked if p == "You are a founder."]
    assert generic == ["best crm", "top crm tools", "which crm should I pick"]
    assert founder == ["best crm"]  # persona cells: one sample
    search = db_session.exec(select(Result).where(
        Result.run_id == run_id, Result.variant == ResultVariant.search)).all()
    assert len(search) == 4 and {r.query_text for r in search} == {"best crm"}
    assert db_session.get(Run, run_id).status == RunStatus.complete


def test_monitor_takes_one_sample(db_session, job_env, monkeypatch):  # noqa: F811
    from worker.jobs import run_mode_a

    calls: list[str] = []

    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s,
                    web_search=True, force_search=True):
        calls.append(query_text)
        return RetrievalOutcome(payload=FIXTURE, parsed=parse_responses_payload(FIXTURE),
                                latency_ms=1)

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)
    t = _setup(db_session, "monitor")
    run_mode_a(_pending_run(db_session, t))
    assert "top crm tools" not in calls and "which crm should I pick" not in calls


def test_yaml_import_keeps_paraphrases(db_session):
    from api.yaml_import import import_config, parse_config_yaml

    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    spec = parse_config_yaml("""
brand: {name: Acme, domains: [acme.com]}
personas: [{name: Generic, prompt: "", segment: generic}]
queries:
  - text: best crm
    paraphrases: ["which crm should I pick", "  ", "top crm tools"]
""")
    import_config(db_session, t, spec)
    q = db_session.exec(select(Query).where(Query.tenant_id == t.id)).one()
    assert q.paraphrases == ["which crm should I pick", "top crm tools"]
