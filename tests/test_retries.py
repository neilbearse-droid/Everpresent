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
