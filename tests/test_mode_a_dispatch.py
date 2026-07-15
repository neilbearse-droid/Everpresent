"""The generalized Mode A dispatch routes each surface to its provider adapter,
applies the search-disabled twin only where the provider supports it, and skips
surfaces whose key is unset — all without a live call (§11.5)."""

import pytest
from sqlmodel import Session, select

from api.models import (
    Persona,
    Query,
    Result,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
)
from engine.retrievers.openai_api import ParsedResponse, RetrievalOutcome

A_SURFACES = ["openai_api", "perplexity_api", "claude_api", "gemini_api"]


def _make_multi_tenant(db_session: Session) -> Tenant:
    tenant = Tenant(
        name="Smith",
        slug="smith",
        clerk_org_id="org_smith",
        ai_processing_approved=True,
        approved_surfaces=list(A_SURFACES),
    )
    db_session.add(tenant)
    db_session.commit()
    assert tenant.id is not None
    for code in A_SURFACES:
        db_session.add(TenantSurface(tenant_id=tenant.id, code=SurfaceCode(code), enabled=True))
    db_session.add(Query(tenant_id=tenant.id, text="best MBA in Canada?"))
    db_session.add(
        Persona(tenant_id=tenant.id, name="applicant", prompt_text="You are an applicant.",
                segment_tag="seg0")
    )
    db_session.commit()
    return tenant


def _fake_for(surface: str):
    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s, web_search=True):
        return RetrievalOutcome(
            payload={"surface": surface},
            parsed=ParsedResponse(
                text=f"{surface} says hello", input_tokens=10, output_tokens=5,
                web_search_calls=1 if web_search else 0, model=model,
            ),
            latency_ms=7,
        )

    return _fake


@pytest.fixture()
def multi_env(db_session, monkeypatch, tmp_path):
    from api.config import get_settings

    for var in ("OPENAI_API_KEY", "PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "k-not-real")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())
    for surface in A_SURFACES:
        monkeypatch.setattr(f"engine.retrievers.{surface}.retrieve", _fake_for(surface))
    yield
    get_settings.cache_clear()


def _pending_multi_run(db_session, tenant) -> int:
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.pending,
              surface_set=list(A_SURFACES), mode_set=["A"])
    db_session.add(run)
    db_session.commit()
    assert run.id is not None
    return run.id


def test_dispatch_routes_every_surface(db_session, multi_env):
    from worker.jobs import run_mode_a

    tenant = _make_multi_tenant(db_session)
    run_id = _pending_multi_run(db_session, tenant)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete

    results = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    search = [r for r in results if r.variant == ResultVariant.search]
    nosearch = [r for r in results if r.variant == ResultVariant.nosearch]

    # One search result per surface (1 query × 1 persona × 4 surfaces).
    assert {r.surface.value for r in search} == set(A_SURFACES)
    # The dual-query twin applies to every provider EXCEPT Perplexity (Sonar
    # always searches), so 3 nosearch results, none of them Perplexity.
    assert {r.surface.value for r in nosearch} == {"openai_api", "claude_api", "gemini_api"}
    assert all(r.surface.value != "perplexity_api" for r in nosearch)


def test_unconfigured_surface_is_skipped_not_crashed(db_session, multi_env, monkeypatch):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    # Drop the Gemini key: its surface is enabled but must be skipped, and the
    # run still completes on the other three providers.
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    tenant = _make_multi_tenant(db_session)
    run_id = _pending_multi_run(db_session, tenant)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete
    assert run.counts.get("skipped_unconfigured") == 1
    surfaces = {
        r.surface.value
        for r in db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    }
    assert "gemini_api" not in surfaces
    assert {"openai_api", "perplexity_api", "claude_api"} <= surfaces
