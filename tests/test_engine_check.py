"""Engine smoke test: one live call per enabled engine, results feed the
admin readiness table."""

import pytest
from sqlmodel import select

from api.models import EngineCheck, SpendEntry, Tenant, TenantSurface
from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome


@pytest.fixture()
def job_env(db_session, monkeypatch):
    monkeypatch.setattr("worker.smoke.get_engine", lambda: db_session.get_bind())


@pytest.fixture()
def as_superadmin(login, db_session):
    from api.models import User

    u = User(email="root@x.test", clerk_user_id="u_root", is_superadmin=True)
    db_session.add(u)
    db_session.commit()
    login(u)
    return u


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme", plan="command", ai_processing_approved=True,
               approved_surfaces=["openai_api", "claude_api"])
    db.add(t)
    db.commit()
    for code in ("openai_api", "claude_api"):
        db.add(TenantSurface(tenant_id=t.id, code=code, enabled=True))
    db.commit()
    return t


def test_smoke_records_pass_parse_problem_and_missing_key(db_session, job_env, monkeypatch):
    from worker import smoke

    async def good(*_a, **_k):
        return RetrievalOutcome(payload={}, latency_ms=5, parsed=ParsedResponse(
            text="GoDaddy and Namecheap.", citations=[ParsedCitation(url="https://a.test/x")],
            web_search_calls=1, input_tokens=10, output_tokens=10, model="gpt-x-served"))

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", good)
    monkeypatch.setattr("worker.smoke.get_settings", lambda: _settings(openai="sk", claude=""))
    t = _tenant(db_session)
    assert smoke.run_engine_smoke(t.id) == 2
    rows = {r.surface: r for r in db_session.exec(select(EngineCheck)).all()}
    assert rows["openai_api"].status == "ok" and rows["openai_api"].served_model == "gpt-x-served"
    assert rows["claude_api"].status == "not_configured"
    assert db_session.exec(select(SpendEntry)).first().kind == "engine_check"


def test_smoke_flags_parse_problems_and_explains_failures():
    from worker.smoke import _verdict, explain_failure

    assert _verdict("", 0, 0, True)[0] == "parse_problem"
    assert _verdict("text", 0, 0, True)[0] == "parse_problem"
    assert _verdict("text", 2, 1, True)[0] == "ok"
    msg = explain_failure(RuntimeError("BrowserType.launch: Executable doesn't exist at /x"))
    assert msg.startswith("The browser isn't installed")


def test_readiness_uses_newer_check(client, as_superadmin, db_session):
    t = _tenant(db_session)
    db_session.add(EngineCheck(tenant_id=t.id, surface="openai_api", status="ok",
                               latency_ms=900, served_model="gpt-x", citations=3))
    db_session.add(EngineCheck(tenant_id=t.id, surface="claude_api", status="parse_problem",
                               detail="no sources"))
    db_session.commit()
    payload = client.get("/api/admin/tenants/acme/readiness").json()
    engines = {e["code"]: e for e in payload["engines"]}
    assert engines["openai_api"]["verdict"] == "check_ok"
    assert engines["openai_api"]["check"]["model"] == "gpt-x"
    assert engines["claude_api"]["verdict"] == "check_parse"


def _settings(openai: str, claude: str):
    from api.config import Settings

    return Settings(openai_api_key=openai, anthropic_api_key=claude)
