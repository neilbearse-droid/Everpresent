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
