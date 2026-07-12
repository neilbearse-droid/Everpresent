"""M2 run pipeline: trigger governance, dispatch job, spend cap, raw storage,
and run-read isolation. No live provider calls — the retriever is faked with
the recorded fixture (§11.5)."""

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from api.models import (
    Citation,
    Persona,
    Query,
    Result,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
    User,
)
from api.runs_service import create_run
from engine.retrievers.openai_api import RetrievalOutcome, parse_responses_payload

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "openai_responses_web_search.json").read_text()
)


def make_tenant(
    db_session: Session,
    slug: str = "smith",
    *,
    approved: bool = True,
    org: str | None = "org_smith",
    queries: int = 2,
    personas: int = 2,
) -> Tenant:
    tenant = Tenant(
        name=slug.title(),
        slug=slug,
        clerk_org_id=org,
        ai_processing_approved=approved,
        approved_surfaces=[SurfaceCode.openai_api.value],
    )
    db_session.add(tenant)
    db_session.commit()
    assert tenant.id is not None
    db_session.add(TenantSurface(tenant_id=tenant.id, code=SurfaceCode.openai_api, enabled=True))
    for i in range(queries):
        db_session.add(Query(tenant_id=tenant.id, text=f"{slug} query {i}"))
    for i in range(personas):
        db_session.add(
            Persona(
                tenant_id=tenant.id,
                name=f"persona {i}",
                prompt_text=f"You are persona {i}.",
                segment_tag=f"seg{i}",
            )
        )
    db_session.commit()
    return tenant


@pytest.fixture()
def superadmin(db_session):
    user = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def as_superadmin(login, superadmin):
    login(superadmin)
    return superadmin


@pytest.fixture()
def enqueue_spy(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr("api.routes.admin.enqueue_run", calls.append)
    return calls


@pytest.fixture()
def job_env(db_session, monkeypatch, tmp_path):
    """Point the worker job at the test DB, a temp raw-storage dir, and a
    fake API key; restore the settings cache afterwards."""
    from api.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())
    yield tmp_path / "raw"
    get_settings.cache_clear()


@pytest.fixture()
def fake_retrieve(monkeypatch):
    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s):
        return RetrievalOutcome(
            payload=FIXTURE, parsed=parse_responses_payload(FIXTURE), latency_ms=42
        )

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)


# --- trigger governance -----------------------------------------------------


def test_gated_tenant_run_is_recorded_not_skipped(client, as_superadmin, enqueue_spy, db_session):
    make_tenant(db_session, approved=False)
    resp = client.post("/api/admin/tenants/smith/runs")
    assert resp.status_code == 201
    assert resp.json()["status"] == "gated"
    assert "governance" in resp.json()["error"]
    assert enqueue_spy == []  # recorded, never dispatched
    assert db_session.exec(select(Run)).one().status == RunStatus.gated


def test_approved_tenant_run_enqueues(client, as_superadmin, enqueue_spy, db_session):
    make_tenant(db_session, approved=True)
    resp = client.post("/api/admin/tenants/smith/runs")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["surface_set"] == ["openai_api"]
    assert enqueue_spy == [body["id"]]


def test_approved_but_no_eligible_surface(client, as_superadmin, enqueue_spy, db_session):
    tenant = make_tenant(db_session, approved=True)
    surface = db_session.exec(
        select(TenantSurface).where(TenantSurface.tenant_id == tenant.id)
    ).one()
    surface.enabled = False
    db_session.add(surface)
    db_session.commit()
    resp = client.post("/api/admin/tenants/smith/runs")
    assert resp.json()["status"] == "failed"
    assert enqueue_spy == []


# --- the job -----------------------------------------------------------------


def _pending_run(db_session, tenant) -> int:
    run = create_run(db_session, tenant)
    db_session.commit()
    db_session.refresh(run)
    assert run.status == RunStatus.pending and run.id is not None
    return run.id


def test_job_stores_results_citations_and_raw(db_session, job_env, fake_retrieve):
    from worker.jobs import run_mode_a

    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete
    assert run.counts == {
        "planned": 4,  # 2 queries × 2 personas × 1 surface
        "completed": 4,
        "failed": 0,
        "withheld_by_cap": 0,
        "citations": 8,
    }
    assert run.cost_usd > 0
    assert run.started_at is not None and run.finished_at is not None

    results = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    assert len(results) == 4
    for result in results:
        assert result.tenant_id == tenant.id
        assert result.response_hash and result.latency_ms == 42
        assert result.query_text and result.persona_name  # snapshot by value
        envelope_path = job_env / result.raw_uri
        assert envelope_path.is_file()
        envelope = json.loads(envelope_path.read_text())
        assert envelope["response"] == FIXTURE
        assert "Smith School of Business" in envelope["parsed_text"]

    citations = db_session.exec(select(Citation)).all()
    assert len(citations) == 8
    assert {c.domain for c in citations} == {"ft.com", "smith.queensu.ca"}


def test_job_respects_spend_cap_pre_dispatch(db_session, job_env, fake_retrieve):
    from worker.jobs import run_mode_a

    tenant = make_tenant(db_session)
    tenant.monthly_spend_cap_usd = 0.0
    db_session.add(tenant)
    db_session.commit()
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.capped
    assert run.counts["withheld_by_cap"] == 4
    assert run.counts["completed"] == 0
    assert db_session.exec(select(Result)).all() == []  # nothing dispatched


def test_job_fails_loudly_without_api_key(db_session, job_env, fake_retrieve, monkeypatch):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)
    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.failed
    assert "OPENAI_API_KEY" in (run.error or "")


def test_failed_calls_are_data_not_crashes(db_session, job_env, monkeypatch):
    from worker.jobs import run_mode_a

    async def _boom(persona_prompt, query_text, *, api_key, model, timeout_s):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _boom)
    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.failed
    results = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    assert len(results) == 4
    assert all(r.status == "error" and "provider exploded" in (r.error or "") for r in results)


# --- read isolation ----------------------------------------------------------


def test_run_reads_are_tenant_scoped(client, login, db_session, job_env, fake_retrieve):
    from worker.jobs import run_mode_a

    tenant_a = make_tenant(db_session, "tenant-a", org="org_a")
    tenant_b = make_tenant(db_session, "tenant-b", org="org_b", queries=1, personas=1)
    run_a = _pending_run(db_session, tenant_a)
    run_b = _pending_run(db_session, tenant_b)
    run_mode_a(run_a)
    run_mode_a(run_b)

    member = User(email="m@a.example", clerk_user_id="user_m")
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)
    login(member, org_id="org_a")

    runs = client.get("/api/tenant/runs").json()
    assert [r["id"] for r in runs] == [run_a]

    assert client.get(f"/api/tenant/runs/{run_a}").status_code == 200
    assert client.get(f"/api/tenant/runs/{run_b}").status_code == 404

    result_b = db_session.exec(select(Result).where(Result.run_id == run_b)).first()
    assert result_b is not None
    assert client.get(f"/api/tenant/results/{result_b.id}/raw").status_code == 404

    detail = client.get(f"/api/tenant/runs/{run_a}").json()
    first_result = detail["results"][0]["result"]
    raw = client.get(f"/api/tenant/results/{first_result['id']}/raw")
    assert raw.status_code == 200
    assert raw.json()["response"]["model"] == "gpt-4o-2024-08-06"
