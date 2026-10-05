"""Fan-out searches from every API engine that reports them."""

from sqlmodel import select

from api.models import Result, ResultStatus, ResultVariant, Run, RunStatus, SurfaceCode, Tenant


def test_claude_searches_are_read():
    from engine.retrievers.claude_api import parse_claude_payload

    payload = {"content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "cheap domains"}},
        {"type": "web_search_tool_result", "content": []},
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "cheap domains"}},
        {"type": "server_tool_use", "name": "web_search",
         "input": {"query": "domain renewal prices"}},
        {"type": "text", "text": "Try GoDaddy."}], "usage": {}}
    assert parse_claude_payload(payload).fanout_queries == ["cheap domains",
                                                            "domain renewal prices"]


def test_chatgpt_batched_searches_are_read():
    from engine.retrievers.openai_api import parse_responses_payload

    payload = {"output": [
        {"type": "web_search_call", "action": {"type": "search", "query": "a",
                                                "queries": ["a", "b", "c"]}},
        {"type": "web_search_call", "action": {"type": "search", "query": "d"}},
    ]}
    assert parse_responses_payload(payload).fanout_queries == ["a", "b", "c", "d"]


def test_reprocessing_backfills_claude_searches(db_session, monkeypatch):
    from api.processing_service import process_run

    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=t.id, query_text="q", persona_name="generic",
               surface=SurfaceCode.claude_api, variant=ResultVariant.search,
               status=ResultStatus.ok, raw_uri="x")
    db_session.add(r)
    db_session.commit()
    stored = {"parsed_text": "Acme is good.", "response": {"content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "acme review"}},
        {"type": "text", "text": "Acme is good."}], "usage": {}}}
    monkeypatch.setattr("api.processing_service._envelope", lambda result, session: stored)
    process_run(db_session, run)
    assert db_session.exec(select(Result)).one().fanout_queries == ["acme review"]


def test_reprocess_route_queues(client, login, db_session, monkeypatch):
    from api.models import User

    calls = []
    monkeypatch.setattr("api.queue.enqueue_reprocess", lambda tid: calls.append(tid))
    t = Tenant(name="Acme", slug="acme")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([t, admin])
    db_session.commit()
    login(admin)
    assert client.post("/api/admin/tenants/acme/reprocess").status_code == 202
    assert calls == [t.id]
