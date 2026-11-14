"""Week-one prompt-set fixes from the October 2026 sweep: the brand-naming rule
applies to imports (B1), repeated samples reach every paraphrase and record the
wording asked (B2), and the natural probe fraction follows the plan (gap 4)."""

import json
from pathlib import Path

from sqlmodel import select

from api.models import BrandProfile, Persona, Query, Result, ResultVariant, Tenant, User
from api.yaml_import import auto_branded_texts, import_config, parse_config_yaml
from engine.retrievers.openai_api import RetrievalOutcome, parse_responses_payload
from tests.test_runs import FIXTURE, _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401

SEEDS = Path(__file__).resolve().parents[1] / "seeds"

ACME_YAML = """
brand:
  name: Acme Labs
  aliases: [Acme CRM]
  domains: [acme.com]
personas: [{name: Generic, prompt: "", segment: generic}]
queries:
  - text: "What is the best CRM for startups?"
  - text: "Acme vs HubSpot: which CRM is better?"          # names the brand, suffix dropped
  - text: "Is Acme CRM worth it for a five-person team?"   # names an alias
  - text: "Does acme.com have a free tier?"                # names the domain
  - text: "Is Acme Labs secure?"
    corpus: brand
    branded: true                                          # explicit flag kept
  - text: "Is Acmeville a real place?"                     # brand only as part of a word
"""

NAMES_BRAND = {
    "Acme vs HubSpot: which CRM is better?",
    "Is Acme CRM worth it for a five-person team?",
    "Does acme.com have a free tier?",
}


# --- B1: the import files brand-naming questions as branded -----------------


def test_import_files_brand_naming_questions_as_branded(db_session):
    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    spec = parse_config_yaml(ACME_YAML)
    assert set(auto_branded_texts(spec)) == NAMES_BRAND

    counts = import_config(db_session, t, spec)
    db_session.commit()
    assert counts["queries"] == 6 and counts["branded_auto"] == 3
    by_text = {q.text: q for q in db_session.exec(select(Query).where(Query.tenant_id == t.id))}
    assert {text for text, q in by_text.items() if q.branded} == NAMES_BRAND | {
        "Is Acme Labs secure?"
    }
    assert by_text["Is Acmeville a real place?"].branded is False
    # The file's corpus is kept; only the layer changes.
    assert by_text["Acme vs HubSpot: which CRM is better?"].corpus_tag == "core"


def test_import_routes_list_the_questions_they_moved(db_session, client, login):
    admin = User(email="neil@example.com", clerk_user_id="u_sa_w1", is_superadmin=True)
    db_session.add(admin)
    db_session.add(Tenant(name="Acme", slug="acme"))
    db_session.commit()
    db_session.refresh(admin)
    login(admin)

    resp = client.post("/api/admin/tenants/acme/import-yaml", content=ACME_YAML,
                       headers={"Content-Type": "text/plain"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"]["branded_auto"] == 3
    assert set(body["auto_branded"]) == NAMES_BRAND


def test_bundled_seeds_leave_nothing_for_the_rule_to_catch():
    """Every bundled config already flags its brand-naming questions, so the
    demo headline is the competitive layer and nothing else."""
    for path in sorted(SEEDS.glob("*.yaml")):
        if "example" in path.stem:
            continue
        spec = parse_config_yaml(path.read_text(encoding="utf-8"))
        assert auto_branded_texts(spec) == [], path.name


def test_recheck_flags_stored_questions_and_reports_them(db_session, client, login):
    """Rows imported before the rule existed are corrected in place: the
    endpoint lists what flipped and leaves explicit choices alone."""
    admin = User(email="neil@example.com", clerk_user_id="u_sa_w2", is_superadmin=True)
    t = Tenant(name="Acme", slug="acme")
    db_session.add_all([admin, t])
    db_session.commit()
    db_session.refresh(admin)
    login(admin)
    db_session.add(BrandProfile(tenant_id=t.id, brand_name="Acme Labs",
                                aliases=["Acme CRM"], domains=["acme.com"]))
    db_session.add(Query(tenant_id=t.id, text="Acme vs HubSpot: which CRM is better?"))
    db_session.add(Query(tenant_id=t.id, text="What is the best CRM for startups?"))
    db_session.add(Query(tenant_id=t.id, text="Is Acme Labs secure?", branded=True))
    db_session.commit()

    resp = client.post("/api/admin/tenants/acme/queries/recheck-branded")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"flagged": ["Acme vs HubSpot: which CRM is better?"], "count": 1}
    db_session.expire_all()
    rows = db_session.exec(select(Query).where(Query.tenant_id == t.id)).all()
    flags = {q.text: q.branded for q in rows}
    assert flags == {
        "Acme vs HubSpot: which CRM is better?": True,
        "What is the best CRM for startups?": False,
        "Is Acme Labs secure?": True,
    }
    # Idempotent: a second pass has nothing left to flip.
    assert client.post("/api/admin/tenants/acme/queries/recheck-branded").json()["count"] == 0


# --- B2: repeated samples reach every paraphrase and record the wording -----


def _sampling_tenant(db_session, plan: str, paraphrases: list[str]) -> Tenant:
    t = make_tenant(db_session, queries=0, personas=0)
    t.plan = plan
    db_session.add(t)
    db_session.add(Persona(tenant_id=t.id, name="Generic", prompt_text="", segment_tag="generic"))
    db_session.add(Query(tenant_id=t.id, text="best crm", paraphrases=paraphrases))
    db_session.commit()
    return t


def test_two_samples_reach_both_paraphrases_across_runs(db_session, job_env, monkeypatch):  # noqa: F811
    from worker.jobs import run_mode_a

    asked: list[str] = []

    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s,
                    web_search=True, force_search=True):
        if web_search and force_search:
            asked.append(query_text)
        return RetrievalOutcome(payload=FIXTURE, parsed=parse_responses_payload(FIXTURE),
                                latency_ms=1)

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)
    paraphrases = ["which crm should I pick", "top crm tools"]
    t = _sampling_tenant(db_session, "diagnose", paraphrases)  # samples_per_cell = 2

    stored: list[set[str]] = []
    for _ in range(2):
        run_id = _pending_run(db_session, t)
        run_mode_a(run_id)
        search = db_session.exec(select(Result).where(
            Result.run_id == run_id, Result.variant == ResultVariant.search)).all()
        assert len(search) == 2 and {r.query_text for r in search} == {"best crm"}
        stored.append({r.asked_text for r in search})
        for r in search:  # the envelope still carries the wording as `asked`
            envelope = json.loads((job_env / r.raw_uri).read_text())
            assert envelope["asked"] == r.asked_text and envelope["query"] == "best crm"

    # Each run: the canonical text once plus one paraphrase; the second run
    # rotates to the other paraphrase instead of repeating the first.
    assert asked.count("best crm") == 2
    assert sorted(w for w in asked if w != "best crm") == sorted(paraphrases)
    assert all("best crm" in s and len(s) == 2 for s in stored)
    assert set.union(*stored) == {"best crm", *paraphrases}


def test_sample_without_paraphrases_repeats_the_canonical_text(db_session, job_env,  # noqa: F811
                                                               fake_retrieve):  # noqa: F811
    from worker.jobs import run_mode_a

    t = _sampling_tenant(db_session, "diagnose", [])
    run_id = _pending_run(db_session, t)
    run_mode_a(run_id)
    search = db_session.exec(select(Result).where(
        Result.run_id == run_id, Result.variant == ResultVariant.search)).all()
    assert [r.asked_text for r in search] == ["best crm", "best crm"]


# --- Gap 4: the natural probe fraction follows the plan ---------------------


def _natural(db_session, run_id) -> list[Result]:
    return db_session.exec(select(Result).where(
        Result.run_id == run_id, Result.variant == ResultVariant.natural)).all()


def test_diagnose_probes_a_rotating_third_regardless_of_the_setting(db_session, job_env,  # noqa: F811
                                                                    fake_retrieve, monkeypatch):  # noqa: F811
    from api.config import get_settings
    from worker.jobs import run_mode_a

    monkeypatch.setenv("NATURAL_PROBE_FRACTION", "0")
    get_settings.cache_clear()
    t = make_tenant(db_session, queries=6, personas=1)
    t.plan = "diagnose"
    db_session.add(t)
    db_session.commit()
    # A third of the queries get an unforced answer each run on the forced
    # engine (OpenAI here); the slice rotates, so three runs cover them all.
    seen: set[str] = set()
    for _ in range(3):
        run_id = _pending_run(db_session, t)
        run_mode_a(run_id)
        probed = {r.query_text for r in _natural(db_session, run_id)}
        assert len(probed) == 2
        seen |= probed
    assert seen == {f"smith query {i}" for i in range(6)}


def test_monitor_keeps_the_deployment_setting(db_session, job_env, fake_retrieve,  # noqa: F811
                                              monkeypatch):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    t = make_tenant(db_session, queries=6, personas=1)
    t.plan = "monitor"
    db_session.add(t)
    db_session.commit()

    monkeypatch.setenv("NATURAL_PROBE_FRACTION", "0")
    get_settings.cache_clear()
    run_id = _pending_run(db_session, t)
    run_mode_a(run_id)
    assert _natural(db_session, run_id) == []

    monkeypatch.setenv("NATURAL_PROBE_FRACTION", "0.34")
    get_settings.cache_clear()
    run_id = _pending_run(db_session, t)
    run_mode_a(run_id)
    assert len(_natural(db_session, run_id)) == 2  # a third of six, as on Render
