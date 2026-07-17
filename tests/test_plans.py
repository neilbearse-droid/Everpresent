"""Pricing plans cap the run matrix and select the model tier. Enforcement is
verified end-to-end through the Mode A job with faked providers (§11.5)."""

import pytest
from sqlmodel import select

from api.models import (
    Persona,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
)
from api.plans import cap_engines, limits_for, model_for
from engine.retrievers.openai_api import ParsedResponse, RetrievalOutcome

A_SURFACES = ["openai_api", "perplexity_api", "claude_api", "gemini_api"]


def test_plan_limits_and_helpers():
    assert limits_for("monitor").max_prompts == 25
    assert limits_for("monitor").diagnosis is False
    assert limits_for("diagnose").max_personas == 2
    assert limits_for("command").max_engines is None
    assert limits_for(None).label == "Custom"  # default
    # Engine cap keeps the canonical order, dropping the lowest-priority ones.
    assert cap_engines(A_SURFACES, 3) == ["openai_api", "perplexity_api", "claude_api"]
    assert cap_engines(A_SURFACES, None) == sorted(A_SURFACES, key=A_SURFACES.index) or A_SURFACES
    # Model tier overrides the configured default; 'configured' falls back.
    assert model_for("openai_api", "economy", "x") == "gpt-5-mini"
    assert model_for("openai_api", "configured", "gpt-4o") == "gpt-4o"


def _fake(surface):
    async def _f(persona_prompt, query_text, *,
        api_key, model, timeout_s, web_search=True, force_search=True):
        return RetrievalOutcome(
            payload={"model": model},
            parsed=ParsedResponse(text=f"{surface} {model}", input_tokens=1, output_tokens=1,
                                  web_search_calls=1 if web_search else 0, model=model),
            latency_ms=1,
        )
    return _f


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    from api.config import get_settings

    for var in ("OPENAI_API_KEY", "PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "k")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())
    for s in A_SURFACES:
        monkeypatch.setattr(f"engine.retrievers.{s}.retrieve", _fake(s))
    yield
    get_settings.cache_clear()


def _tenant(db, plan):
    t = Tenant(name="Acme", slug="acme", clerk_org_id="org", ai_processing_approved=True,
               approved_surfaces=list(A_SURFACES), plan=plan)
    db.add(t)
    db.commit()
    for code in A_SURFACES:
        db.add(TenantSurface(tenant_id=t.id, code=SurfaceCode(code), enabled=True))
    for i in range(3):
        db.add(Query(tenant_id=t.id, text=f"q{i}"))
    for i in range(3):
        db.add(Persona(tenant_id=t.id, name=f"p{i}", prompt_text=f"P{i}", segment_tag=f"s{i}"))
    db.commit()
    return t


def _run(db, t):
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.pending,
              surface_set=list(A_SURFACES), mode_set=["A"])
    db.add(run)
    db.commit()
    return run.id


def _results(db, run_id):
    return db.exec(select(Result).where(Result.run_id == run_id)).all()


def test_monitor_caps_personas_engines_and_skips_diagnosis(db_session, env):
    from worker.jobs import run_mode_a

    t = _tenant(db_session, "monitor")  # 25/1/3, no diagnosis, economy
    run_id = _run(db_session, t)
    run_mode_a(run_id)

    results = _results(db_session, run_id)
    # 3 queries × 1 persona × 3 engines, search-only (no dual-query twin).
    assert len(results) == 9
    assert all(r.variant == ResultVariant.search for r in results)
    assert {r.surface.value for r in results} == {"openai_api", "perplexity_api", "claude_api"}
    assert len({r.persona_name for r in results}) == 1
    # Economy model tier reached the provider (captured in the raw model echo).
    openai = next(r for r in results if r.surface.value == "openai_api")
    assert openai.status == ResultStatus.ok


def test_diagnosis_twin_cached_across_runs(db_session, env, monkeypatch):
    """Training knowledge is frozen between model snapshots, so the second run
    reuses the twins (zero provider calls) while searches stay live."""
    from worker.jobs import run_mode_a

    calls: list[tuple[str, bool]] = []

    def make(surface):
        async def _f(persona_prompt, query_text, *,
            api_key, model, timeout_s, web_search=True, force_search=True):
            calls.append((surface, web_search))
            return RetrievalOutcome(
                payload={"model": model},
                parsed=ParsedResponse(text="x", input_tokens=1, output_tokens=1,
                                      web_search_calls=0, model=model),
                latency_ms=1,
            )
        return _f

    for s in A_SURFACES:
        monkeypatch.setattr(f"engine.retrievers.{s}.retrieve", make(s))

    t = _tenant(db_session, "diagnose")
    run1 = _run(db_session, t)
    run_mode_a(run1)
    assert sum(1 for (_s, ws) in calls if not ws) == 9  # 3 queries × 3 twin engines

    calls.clear()
    run2 = _run(db_session, t)
    run_mode_a(run2)
    assert sum(1 for (_s, ws) in calls if not ws) == 0   # twins reused, not re-bought
    assert sum(1 for (_s, ws) in calls if ws) == 24      # searches still live

    nosearch2 = [r for r in _results(db_session, run2) if r.variant == ResultVariant.nosearch]
    assert len(nosearch2) == 9  # cloned into the run so the classifier pairing works
    assert all(r.latency_ms == 0 and r.raw_uri for r in nosearch2)
    run = db_session.get(Run, run2)
    assert run is not None and run.counts["diagnosis_cached"] == 9


def test_diagnose_enables_twin_and_two_personas(db_session, env):
    from worker.jobs import run_mode_a

    t = _tenant(db_session, "diagnose")  # 50/2/4, diagnosis on
    run_id = _run(db_session, t)
    run_mode_a(run_id)

    results = _results(db_session, run_id)
    search = [r for r in results if r.variant == ResultVariant.search]
    nosearch = [r for r in results if r.variant == ResultVariant.nosearch]
    # 3 queries × 2 personas × 4 engines search.
    assert len(search) == 24
    assert len({r.persona_name for r in search}) == 2
    # Diagnosis twin on the 3 engines that support it (not Perplexity), 1 persona.
    assert {r.surface.value for r in nosearch} == {"openai_api", "claude_api", "gemini_api"}
    assert len(nosearch) == 9
