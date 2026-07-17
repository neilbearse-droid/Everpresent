"""Query fan-out (§AEO-plan M1): capture the sub-queries engines issue, feed
them into briefs, and surface them per prompt."""

from api.dashboards_service import action_plan, fanout_report
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
from engine.retrievers.gemini_api import parse_gemini_payload
from engine.retrievers.openai_api import parse_responses_payload


def test_gemini_parser_captures_fanout():
    payload = {
        "candidates": [{
            "content": {"parts": [{"text": "Smith is a top MBA."}]},
            "groundingMetadata": {
                "groundingChunks": [{"web": {"uri": "https://ft.com/x", "title": "FT"}}],
                "webSearchQueries": ["best MBA Canada", "Smith School ranking 2026"],
            },
        }],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
        "modelVersion": "gemini-x",
    }
    parsed = parse_gemini_payload(payload)
    assert parsed.fanout_queries == ["best MBA Canada", "Smith School ranking 2026"]


def test_openai_parser_captures_fanout_from_search_actions():
    payload = {
        "output": [
            {"type": "web_search_call", "action": {"type": "search", "query": "smith mba cost"}},
            {"type": "message", "content": [
                {"type": "output_text", "text": "It costs $95k.", "annotations": []},
            ]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 8},
        "model": "gpt-x",
    }
    parsed = parse_responses_payload(payload)
    assert parsed.fanout_queries == ["smith mba cost"]


def _result(db, run_id, tid, qtext, surface, *, fanout) -> Result:
    r = Result(run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant.search,
               status=ResultStatus.ok, fanout_queries=fanout)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_fanout_report_dedupes_across_engines(db_session):
    tenant = Tenant(name="Smith", slug="smith")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Smith", domains=["smith.ca"]))
    db_session.add(Query(tenant_id=tid, text="best mba"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()

    _result(db_session, run.id, tid, "best mba", "gemini_api",
            fanout=["MBA rankings 2026", "best mba"])   # self-query dropped
    _result(db_session, run.id, tid, "best mba", "openai_api",
            fanout=["mba rankings 2026", "Smith tuition"])  # case-dup merged

    rep = fanout_report(db_session, tid)
    assert rep["observed"] is True
    prompt = rep["prompts"][0]
    assert prompt["query"] == "best mba"
    texts = [s["text"].lower() for s in prompt["subqueries"]]
    assert "mba rankings 2026" in texts
    assert "smith tuition" in texts
    assert "best mba" not in texts          # the prompt itself is excluded
    # The shared sub-query is attributed to both engines.
    shared = next(s for s in prompt["subqueries"] if s["text"].lower() == "mba rankings 2026")
    assert set(shared["engines"]) == {"Gemini", "ChatGPT"}


def test_brief_subtopics_prefer_observed_fanout(db_session):
    tenant = Tenant(name="Smith", slug="smith")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Smith", domains=["smith.ca"]))
    db_session.add(Query(tenant_id=tid, text="best mba", corpus_tag="mba"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()

    # Content gap: rival in search, brand in the training twin.
    s = _result(db_session, run.id, tid, "best mba", "gemini_api",
                fanout=["MBA rankings 2026", "MBA employment rate"])
    db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                           entity_name="Rotman", position=0, rank=1))
    ns = Result(run_id=run.id, tenant_id=tid, query_text="best mba", persona_name="p",
                surface=SurfaceCode.gemini_api, variant=ResultVariant.nosearch,
                status=ResultStatus.ok)
    db_session.add(ns)
    db_session.commit()
    db_session.refresh(ns)
    db_session.add(Mention(result_id=ns.id, tenant_id=tid, entity_type="brand",
                           entity_name="Smith", position=0, rank=1))
    db_session.commit()

    brief = action_plan(db_session, tid)["briefs"][0]
    assert brief["subtopics_source"] == "observed"
    assert "MBA rankings 2026" in brief["subtopics"]
