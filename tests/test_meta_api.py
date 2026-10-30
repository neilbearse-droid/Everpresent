"""Meta AI (Muse Spark) via the Meta Model API.

The fixture follows the OpenAI-compatible Responses shape Meta documents; no
live call was possible when this was written, so the engine check on the
worker is the first real test. CI never calls the API or spends."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from engine.costs import estimate_meta_cost_usd
from engine.retrievers import meta_api

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "meta_responses_web_search.json").read_text()
)


def test_parses_text_and_citations():
    parsed = meta_api.parse_meta_payload(FIXTURE)
    assert parsed.text.startswith("For a small bakery")
    assert [c.domain for c in parsed.citations] == ["siteforge.example", "northpeak.example"]
    # No search step in the body, but a cited answer searched.
    assert parsed.web_search_calls == 1
    assert (parsed.input_tokens, parsed.output_tokens) == (2140, 288)
    assert parsed.model == "muse-spark-1.3"


def test_search_steps_and_fanout_are_read_when_listed():
    payload = {**FIXTURE, "output": [
        {"type": "web_search_call", "action": {"query": "bakery website builder"}},
        {"type": "web_search_call", "action": {"queries": ["online ordering bakery site"]}},
        *FIXTURE["output"],
    ]}
    parsed = meta_api.parse_meta_payload(payload)
    assert parsed.web_search_calls == 2
    assert parsed.fanout_queries == ["bakery website builder", "online ordering bakery site"]


def test_uncited_answer_without_search_counts_no_search():
    parsed = meta_api.parse_meta_payload({"output": [{"type": "message", "content": [
        {"type": "output_text", "text": "From memory.", "annotations": []}]}]})
    assert parsed.web_search_calls == 0 and parsed.citations == []


def test_search_is_offered_not_forced():
    body = meta_api.build_request_body("You run a bakery.", "best builder?",
                                       model="muse-spark-1.3")
    assert body["tools"] == [{"type": "web_search"}]
    assert "tool_choice" not in body
    assert body["instructions"] == "You run a bakery."
    twin = meta_api.build_request_body("", "best builder?", model="muse-spark-1.3",
                                       web_search=False)
    assert "tools" not in twin and "instructions" not in twin


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(meta_api.httpx, "AsyncClient", factory)


def test_retrieve_posts_to_meta_and_retries_overload(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json=FIXTURE)

    async def no_sleep(_s: float) -> None:
        return None

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(meta_api.asyncio, "sleep", no_sleep)
    out = asyncio.run(meta_api.retrieve("", "best builder?", api_key="k",
                                        model="muse-spark-1.3"))
    assert str(calls[-1].url) == "https://api.meta.ai/v1/responses"
    assert calls[-1].headers["authorization"] == "Bearer k"
    assert len(calls) == 2 and len(out.parsed.citations) == 2


def test_empty_answer_is_an_error_not_a_miss(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(
        200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                   "output": []}))
    with pytest.raises(RuntimeError, match="no answer text"):
        asyncio.run(meta_api.retrieve("", "q", api_key="k", model="muse-spark-1.3"))


def test_bad_key_names_meta(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(
        401, json={"error": {"message": "Invalid API key", "type": "auth_error"}}))
    with pytest.raises(httpx.HTTPStatusError, match="Meta 401: Invalid API key"):
        asyncio.run(meta_api.retrieve("", "q", api_key="bad", model="muse-spark-1.3"))


def test_cost_estimate():
    # 1M in + 1M out on Muse Spark, plus 4 searches at $2.50 per 1k.
    assert estimate_meta_cost_usd("muse-spark-1.3", 1_000_000, 1_000_000, 4) == 5.51
    assert estimate_meta_cost_usd("muse-wonder-1.0", 1_000_000, 0) == 4.0


def test_engine_is_registered_everywhere():
    from api.dashboards.common import _surface_label
    from api.dashboards.measurement import FORCED_SEARCH_SURFACES
    from api.models import SurfaceCode
    from api.plans import ENGINE_PRIORITY, model_for
    from api.readiness_service import _LABELS, _NEEDS
    from api.runs_service import MODE_A_SURFACES
    from worker.jobs import A_ADAPTERS

    adapter = A_ADAPTERS["meta_api"]
    assert adapter.module is meta_api and adapter.env_var == "META_API_KEY"
    assert not adapter.forces_search and "meta_api" not in FORCED_SEARCH_SURFACES
    assert SurfaceCode.meta_api in MODE_A_SURFACES and "meta_api" in ENGINE_PRIORITY
    assert _NEEDS["meta_api"] and _LABELS["meta_api"] == "Meta AI (API)"
    assert _surface_label("meta_api") == "Meta AI"
    # Never a "-contributor" model: those let Meta train on client questions.
    for tier in ("economy", "standard", "premium"):
        assert "contributor" not in model_for("meta_api", tier, "x")


def test_meta_search_crawler_is_known():
    from engine.agents.bots import classify_user_agent

    bot = classify_user_agent(
        "meta-webindexer/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)")
    assert bot is not None and bot.company == "Meta" and bot.purpose == "search"


def _tenant_with_rates(db, meta_named: int, other_named: int):
    from api.models import BrandProfile, Query, ResultVariant, Run, RunStatus, SurfaceCode, Tenant
    from tests.test_unforced import _answers

    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    assert t.id is not None
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme"))
    for i in range(3):
        db.add(Query(tenant_id=t.id, text=f"q{i}"))
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    assert run.id is not None
    _answers(db, t.id, run.id, SurfaceCode.meta_api, ResultVariant.search, 40,
             named=meta_named, searched=40)
    _answers(db, t.id, run.id, SurfaceCode.claude_api, ResultVariant.search, 40,
             named=other_named, searched=40)
    # ChatGPT's forced answers name Acme every time; only its unforced probe
    # is comparable with Meta's unforced answers.
    _answers(db, t.id, run.id, SurfaceCode.openai_api, ResultVariant.search, 40,
             named=40, searched=40)
    _answers(db, t.id, run.id, SurfaceCode.openai_api, ResultVariant.natural, 40,
             named=other_named, searched=10)
    return t.id


def test_meta_play_fires_on_a_real_gap(db_session):
    from api.recommendations_service import _meta_play

    tid = _tenant_with_rates(db_session, meta_named=4, other_named=20)
    (play,) = _meta_play(db_session, tid)
    assert play.gap_ref == "meta:gap" and play.branch == "meta"
    assert "Meta AI names you in 10.0%" in play.action_text and "in 50.0%" in play.action_text
    assert any("meta-webindexer" in s for s in play.steps)


def test_meta_play_stays_quiet_within_the_noise(db_session):
    from api.recommendations_service import _meta_play

    tid = _tenant_with_rates(db_session, meta_named=18, other_named=20)
    assert _meta_play(db_session, tid) == []
