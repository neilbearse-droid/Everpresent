"""Transient provider failures are retried instead of losing the answer:
Anthropic 529 (overloaded), non-JSON 200 bodies (proxy/CDN error pages) and
SerpApi 429/5xx. Found by the fault-injection battle test."""

import asyncio
import json

import httpx
import pytest


def _resp(status: int, body) -> httpx.Response:
    req = httpx.Request("POST", "http://x")
    if isinstance(body, str):
        return httpx.Response(status, text=body, request=req)
    return httpx.Response(status, content=json.dumps(body).encode(), request=req)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


def _sequence(monkeypatch, method: str, responses: list[httpx.Response]):
    calls = []

    async def _fake(self, *args, **kwargs):
        calls.append(1)
        return responses[len(calls) - 1]

    monkeypatch.setattr(httpx.AsyncClient, method, _fake)
    return calls


CLAUDE_OK = {"content": [{"type": "text", "text": "GoDaddy is popular."}],
             "usage": {"input_tokens": 1, "output_tokens": 1}}


@pytest.mark.parametrize(
    "first", [_resp(529, {"error": "overloaded"}), _resp(200, "<html>bad gateway</html>")]
)
def test_claude_retries_overloaded_and_garbage(monkeypatch, first):
    from engine.retrievers import claude_api

    calls = _sequence(monkeypatch, "post", [first, _resp(200, CLAUDE_OK)])
    out = asyncio.run(claude_api.retrieve("", "best builder?", api_key="k", model="m"))
    assert len(calls) == 2 and "GoDaddy" in out.parsed.text


def test_openai_retries_a_non_json_200(monkeypatch):
    from engine.retrievers import openai_api

    ok = {"status": "completed", "model": "m", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": "Wix and GoDaddy.", "annotations": []}]}], "usage": {}}
    calls = _sequence(monkeypatch, "post", [_resp(200, "<html>oops</html>"), _resp(200, ok)])
    out = asyncio.run(openai_api.retrieve("", "q", api_key="k", model="gpt-4o"))
    assert len(calls) == 2 and out.parsed.text.startswith("Wix")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_serpapi_retries_transient_errors(monkeypatch, status):
    from engine.retrievers import google_aio

    block = {"type": "paragraph", "snippet": "GoDaddy offers domains."}
    ok = {"ai_overview": {"text_blocks": [block],
                          "references": [{"link": "https://www.godaddy.com/", "title": "GoDaddy"}]}}
    calls = _sequence(monkeypatch, "get", [_resp(status, {"error": "x"}), _resp(200, ok)])
    out = asyncio.run(google_aio._capture_serpapi("q", gl="us", hl="en", api_key="k", timeout_s=5))
    assert len(calls) == 2 and "GoDaddy" in out.aio_text


def test_serpapi_gives_up_after_three_attempts(monkeypatch):
    from engine.retrievers import google_aio

    _sequence(monkeypatch, "get", [_resp(500, {})] * 3)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(google_aio._capture_serpapi("q", gl="us", hl="en", api_key="k", timeout_s=5))


def test_utility_llm_retries_529(monkeypatch):
    from engine.llm import router

    seq = [_resp(529, {}), _resp(200, CLAUDE_OK)]
    calls = []

    def _post(self, *a, **k):
        calls.append(1)
        return seq[len(calls) - 1]

    monkeypatch.setattr(httpx.Client, "post", _post)
    monkeypatch.setattr(router, "assert_runtime_model_allowed", lambda _m: None)
    out = router.complete("p", model="m", api_key="k", system="s", max_tokens=10,
                          _sleep=lambda _s: None)
    assert "GoDaddy" in out
    assert len(calls) == 2


AGENT_OK = {
    "model": "perplexity/sonar", "status": "completed",
    "output": [{"type": "message",
                "content": [{"type": "output_text", "text": "GoDaddy and Wix."}]}],
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def test_perplexity_uses_the_agent_api(monkeypatch):
    from engine.retrievers import perplexity_api

    urls: list[str] = []

    async def _post(self, url, *a, **k):
        urls.append(url)
        return _resp(200, AGENT_OK)

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(perplexity_api.retrieve("", "q", api_key="k", model="sonar"))
    assert urls == [perplexity_api.PERPLEXITY_AGENT_URL]
    assert out.parsed.text == "GoDaddy and Wix."


def test_perplexity_falls_back_to_legacy_when_agent_api_rejects(monkeypatch):
    from engine.retrievers import perplexity_api

    legacy = {"model": "sonar", "choices": [{"message": {"content": "Legacy answer."}}],
              "usage": {}}
    urls: list[str] = []

    async def _post(self, url, *a, **k):
        urls.append(url)
        if url == perplexity_api.PERPLEXITY_AGENT_URL:
            return _resp(400, {"error": "model not supported"})
        return _resp(200, legacy)

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(perplexity_api.retrieve("", "q", api_key="k", model="sonar"))
    assert urls == [perplexity_api.PERPLEXITY_AGENT_URL, perplexity_api.PERPLEXITY_URL]
    assert out.parsed.text == "Legacy answer."
    assert "agent_api_http_400" in out.payload["_everpresent_fallback"]


def test_perplexity_failed_run_is_an_error_not_an_empty_answer(monkeypatch):
    from engine.retrievers import perplexity_api

    failed = {"status": "failed", "error": {"message": "search backend unavailable"},
              "output": []}
    _sequence(monkeypatch, "post", [_resp(200, failed)])
    with pytest.raises(RuntimeError, match="failed: search backend unavailable"):
        asyncio.run(perplexity_api.retrieve("", "q", api_key="k", model="sonar"))


def test_serpapi_retries_the_lazy_overview_follow_up(monkeypatch):
    from engine.retrievers import google_aio

    first = {"ai_overview": {"page_token": "tok"}, "organic_results": []}
    full = {"ai_overview": {"text_blocks": [{"type": "paragraph", "snippet": "GoDaddy."}],
                            "references": []}}
    calls = _sequence(monkeypatch, "get", [_resp(200, first), _resp(503, {}), _resp(200, full)])
    out = asyncio.run(google_aio._capture_serpapi("q", gl="us", hl="en", api_key="k", timeout_s=5))
    assert len(calls) == 3 and "GoDaddy" in out.aio_text and out.extra_searches == 1


def test_an_overview_that_never_loads_is_an_error_not_empty(monkeypatch):
    from engine.retrievers import google_aio

    first = {"ai_overview": {"page_token": "tok"}, "organic_results": []}
    _sequence(monkeypatch, "get", [_resp(200, first), _resp(200, {"ai_overview": {}})])
    with pytest.raises(RuntimeError, match="failed to load"):
        asyncio.run(google_aio._capture_serpapi("q", gl="us", hl="en", api_key="k", timeout_s=5))


GEMINI_OK = {"modelVersion": "gemini-3.6-flash", "candidates": [
    {"content": {"parts": [{"text": "GoDaddy and Wix."}]}, "finishReason": "STOP"}],
    "usageMetadata": {}}


def test_gemini3_uses_thinking_level_not_budget():
    from engine.retrievers.gemini_api import build_request_body

    cfg = build_request_body("", "q", model="gemini-3.6-flash")["generationConfig"]
    assert cfg["thinkingConfig"] == {"thinkingLevel": "low"}  # never both (API error)
    assert cfg["maxOutputTokens"] > 1200  # headroom: thinking counts toward the cap
    legacy = build_request_body("", "q", model="gemini-2.5-flash")["generationConfig"]
    assert legacy["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_retired_model_falls_back_to_stable(monkeypatch):
    from engine.retrievers import gemini_api

    urls: list[str] = []

    async def _post(self, url, *a, **k):
        urls.append(url)
        if "gemini-2.5-pro" in url:
            return _resp(404, {"error": {"message": "models/gemini-2.5-pro is not found"}})
        return _resp(200, GEMINI_OK)

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    out = asyncio.run(gemini_api.retrieve("", "q", api_key="k", model="gemini-2.5-pro"))
    assert urls[-1].endswith("/gemini-3.6-flash:generateContent")
    assert "gemini-2.5-pro" in out.payload["_everpresent_model_fallback"]
    assert out.parsed.text == "GoDaddy and Wix."


def test_gemini3_grounding_is_billed_per_query():
    from engine.costs import estimate_gemini_cost_usd

    # 3.6 Flash: $1.50/$7.50 per 1M (conservative list), $14 per 1k queries.
    assert estimate_gemini_cost_usd("gemini-3.6-flash", 1_000_000, 0, 3) == round(
        1.50 + 3 * 14 / 1000, 6)
    assert estimate_gemini_cost_usd("gemini-3.1-pro-preview", 0, 1_000_000, 0) == 12.0


def test_openai_out_of_credits_fails_fast_with_a_clear_reason(monkeypatch):
    from engine.retrievers import openai_api
    from worker.smoke import explain_failure

    quota = _resp(429, {"error": {"message": "You exceeded your current quota",
                                  "type": "insufficient_quota", "code": "insufficient_quota"}})
    calls = _sequence(monkeypatch, "post", [quota, quota, quota])
    with pytest.raises(openai_api.OpenAIQuotaError) as exc:
        asyncio.run(openai_api.retrieve("", "q", api_key="k", model="gpt-4o"))
    assert len(calls) == 1  # no pointless retries
    assert "out of credits" in explain_failure(exc.value)


def test_openai_real_rate_limit_retries_then_names_the_cause(monkeypatch):
    from engine.retrievers import openai_api
    from worker.smoke import explain_failure

    limited = _resp(429, {"error": {"message": "Rate limit reached for requests",
                                    "type": "requests", "code": "rate_limit_exceeded"}})
    calls = _sequence(monkeypatch, "post", [limited, limited, limited])
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(openai_api.retrieve("", "q", api_key="k", model="gpt-4o"))
    assert len(calls) == 3
    msg = explain_failure(exc.value)
    assert "rate_limit_exceeded" in msg and "too many calls" in msg


def test_gemini_zero_quota_fails_fast_with_googles_reason(monkeypatch):
    from engine.retrievers import gemini_api
    from worker.smoke import explain_failure

    zero = _resp(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message":
                                 "Quota exceeded for metric: generate_content_free_tier_requests, "
                                 "limit: 0, model: gemini-3.6-flash"}})
    calls = _sequence(monkeypatch, "post", [zero, zero, zero, zero])
    with pytest.raises(gemini_api.GeminiQuotaError) as exc:
        asyncio.run(gemini_api.retrieve("", "q", api_key="k", model="gemini-3.6-flash"))
    assert len(calls) == 1
    msg = explain_failure(exc.value)
    assert "limit: 0" in msg and "billing" in msg


def test_gemini_minute_limit_retries_and_keeps_googles_message(monkeypatch):
    from engine.retrievers import gemini_api

    busy = _resp(429, {"error": {"status": "RESOURCE_EXHAUSTED",
                                 "message": "Quota exceeded for requests per minute, limit: 10",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                              "retryDelay": "7s"}]}})
    calls = _sequence(monkeypatch, "post", [busy] * 5)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(gemini_api.retrieve("", "q", api_key="k", model="gemini-3.6-flash"))
    assert len(calls) >= 3 and "requests per minute" in str(exc.value)
