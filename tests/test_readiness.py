"""Engine readiness + the wiring fixes behind it: an imported config approves
the surfaces it enables, a missing API key never costs the browser/SERP
surfaces their turn, the readiness verdicts follow the last run's evidence,
and one switch turns the Claude features on."""

from sqlmodel import Session, select

from api.models import (
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
    User,
)
from api.readiness_service import engine_readiness
from api.yaml_import import import_config, parse_config_yaml

YAML = """
brand: {name: GoDaddy, aliases: [], domains: [godaddy.com]}
competitors: [{name: Wix, aliases: [], domains: [wix.com]}]
personas: [{name: Generic, segment: generic, prompt: ""}]
queries: [{text: best website builder}]
surfaces: [openai_api, claude_api, copilot_web, google_aio]
"""


def _tenant(db: Session, **kw) -> Tenant:
    t = Tenant(name="GoDaddy", slug="godaddy", ai_processing_approved=True, **kw)
    db.add(t)
    db.commit()
    import_config(db, t, parse_config_yaml(YAML))
    db.commit()
    db.refresh(t)
    return t


def _verdicts(db, tenant) -> dict[str, str]:
    return {e["code"]: e["verdict"] for e in engine_readiness(db, tenant)["engines"]}


def test_import_approves_the_surfaces_it_enables(db_session):
    t = _tenant(db_session)
    assert set(t.approved_surfaces) == {"openai_api", "claude_api", "copilot_web", "google_aio"}


def test_import_sets_search_country(db_session):
    t = Tenant(name="G", slug="g2")
    db_session.add(t)
    db_session.commit()
    import_config(db_session, t, parse_config_yaml("geo: {country: us}\n" + YAML))
    db_session.commit()
    assert t.aio_geo == {"gl": "us", "hl": "en"}


def test_godaddy_seed_is_us_and_includes_google_aio():
    from pathlib import Path

    spec = parse_config_yaml(Path("seeds/godaddy.yaml").read_text())
    assert spec.geo is not None and spec.geo.country == "us"
    assert SurfaceCode.google_aio in spec.surfaces


def test_verdicts_follow_config_and_last_run_evidence(db_session):
    t = _tenant(db_session)
    v = _verdicts(db_session, t)
    assert v["openai_api"] == "not_run_yet"
    assert v["perplexity_api"] == "off"
    assert v["gemini_web"] == "unavailable"

    run = Run(
        tenant_id=t.id, status=RunStatus.complete,
        surface_set=["openai_api", "claude_api", "copilot_web", "google_aio"],
        mode_set=["A", "B"], counts={"unconfigured:claude_api": 1},
    )
    db_session.add(run)
    db_session.commit()

    def add(surface, status):
        db_session.add(Result(
            run_id=run.id, tenant_id=t.id, query_text="q", persona_name="p",
            surface=SurfaceCode(surface), variant=ResultVariant.search, status=status,
        ))

    add("openai_api", ResultStatus.ok)
    add("copilot_web", ResultStatus.blocked)
    add("google_aio", ResultStatus.error)
    db_session.commit()

    v = _verdicts(db_session, t)
    assert v["openai_api"] == "ready"
    assert v["claude_api"] == "missing_key"
    assert v["copilot_web"] == "blocked"
    assert v["google_aio"] == "error"


def test_plan_engine_cap_is_reported(db_session):
    t = _tenant(db_session, plan="monitor")  # caps runs at 3 engines
    v = _verdicts(db_session, t)
    assert list(v.values()).count("outside_plan") == 1
    checks = {c["label"]: c["ok"] for c in engine_readiness(db_session, t)["checks"]}
    assert checks["Plan allows every engine"] is False


def test_missing_api_keys_still_run_browser_surfaces(db_session, monkeypatch, tmp_path):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())
    queued: list[int] = []
    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", queued.append)

    t = _tenant(db_session)
    run = Run(tenant_id=t.id, status=RunStatus.pending,
              surface_set=["openai_api", "claude_api", "copilot_web"], mode_set=["A", "B"])
    db_session.add(run)
    db_session.commit()
    run_mode_a(run.id)  # type: ignore[arg-type]
    get_settings.cache_clear()

    db_session.refresh(run)
    assert queued == [run.id]  # Mode B still gets its turn
    assert run.status != RunStatus.failed
    assert run.counts["unconfigured:openai_api"] == 1
    assert run.counts["unconfigured:claude_api"] == 1


def test_ai_features_switch(client, db_session, login):
    from api.config import get_settings

    user = User(email="sa@example.com", clerk_user_id="u_sa", is_superadmin=True)
    db_session.add(user)
    db_session.add(Tenant(name="G", slug="g"))
    db_session.commit()
    login(user)
    s = get_settings()

    body = client.post("/api/admin/tenants/g/ai-features", json={"enabled": True}).json()
    assert body["entity_extraction_enabled"] is True
    assert {s.utility_model_extract, s.utility_model_draft} <= set(body["approved_utility_models"])

    body = client.post("/api/admin/tenants/g/ai-features", json={"enabled": False}).json()
    assert body["entity_extraction_enabled"] is False
    models = {s.utility_model_extract, s.utility_model_draft}
    assert not models & set(body["approved_utility_models"])

    assert client.get("/api/admin/tenants/g/readiness").status_code == 200
    body = client.patch("/api/admin/tenants/g", json={"search_country": "US"}).json()
    assert body["aio_geo"]["gl"] == "us"
    assert client.patch("/api/admin/tenants/g", json={"search_country": "usa"}).status_code == 422
    assert db_session.exec(select(TenantSurface)).all() == []  # no surfaces imported for "g"
