"""Mode A retriever: Perplexity Agent API (§6.1).

Perplexity retired the Sonar chat-completions API on 2026-09-27 and replaced
it with the Agent API (`POST /v1/agent`, an OpenAI Responses-style surface).
After that date legacy `/chat/completions` calls were still answered, but
"reformulated as Agent API requests" — so the data changed underneath without
an error. We call the Agent API directly:

- model `perplexity/sonar` with web search FORCED. Perplexity's "presets"
  (fast/low/...) resolve to OpenAI models, so they would measure the wrong
  engine; `sonar-pro` has no Agent API slug and maps here too.
- the persona prompt is `instructions`, the query is `input`.
- web search is an explicit tool, so a search-disabled (training-only) twin is
  possible for the first time: omit the tool.
- citations come from the `search_results` output item; the issued search
  queries are the fan-out.
- failed runs return HTTP 200 with `status: "failed"`, so status is checked.

The legacy chat-completions parser is kept: stored envelopes from before the
switch are re-processed through `parse_perplexity_payload`, which accepts
both shapes. If the Agent API rejects the request outright (400/404/422) the
call falls back once to the legacy endpoint and the payload is tagged, so a
Perplexity-side surprise degrades instead of failing the engine.

Like openai_api, this is a *measured surface*: it calls the provider directly
and deliberately bypasses engine/llm's allowlist router.
"""

import asyncio
import time
from typing import Any

import httpx

from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

PERPLEXITY_AGENT_URL = "https://api.perplexity.ai/v1/agent"
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"  # legacy (fallback only)
# 529 is Anthropic's "overloaded"; common under load, always transient.
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}
# The Agent API rejects unknown models/fields with these; try legacy once.
_FALLBACK_STATUS = {400, 404, 405, 422}

AGENT_MODEL = "perplexity/sonar"
# When Perplexity retired Sonar chat completions; Perplexity numbers before
# and after are different systems (see dashboards' series-break note).
SONAR_RETIRED_ON = "2026-09-27"


def agent_model(model: str) -> str:
    """Map configured names to an Agent API slug. Bare Sonar names (`sonar`,
    `sonar-pro`, ...) are rejected by the Agent API; all map to the one
    Perplexity-native slug so we keep measuring Perplexity's own model."""
    model = (model or "").strip()
    if "/" in model:
        return model
    return AGENT_MODEL


def _parse_agent_payload(payload: dict[str, Any]) -> ParsedResponse:
    texts: list[str] = []
    citations: list[ParsedCitation] = []
    seen: set[str] = set()
    fanout: list[str] = []
    search_items = 0

    def _add(url: Any, title: Any = "") -> None:
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            citations.append(ParsedCitation(url=url, title=str(title or "")))

    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "search_results":
            search_items += 1
            for q in item.get("queries") or []:
                if isinstance(q, str) and q:
                    fanout.append(q)
            for r in item.get("results") or []:
                if isinstance(r, dict):
                    _add(r.get("url"), r.get("title"))
        elif kind == "message":
            for part in item.get("content") or []:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                texts.append(part.get("text", "") or "")
                # Annotations are often empty on Agent responses; use if present.
                for ann in part.get("annotations") or []:
                    if isinstance(ann, dict) and ann.get("type") == "url_citation":
                        _add(ann.get("url"), ann.get("title"))

    usage = payload.get("usage") or {}
    details = usage.get("tool_calls_details") or {}
    # The billing key is reported as both "search_web" and "web_search".
    searches = 0
    for key in ("search_web", "web_search"):
        d = details.get(key)
        if isinstance(d, dict):
            searches = int(d.get("invocation") or d.get("invocations") or d.get("count") or 0)
            if searches:
                break
    if not searches:
        searches = len(fanout) or search_items
    return ParsedResponse(
        text="\n\n".join(t for t in texts if t),
        citations=citations,
        web_search_calls=searches,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        model=payload.get("model", ""),
        fanout_queries=fanout,
    )


def _parse_legacy_payload(payload: dict[str, Any]) -> ParsedResponse:
    choices = payload.get("choices") or []
    text = ""
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""

    citations: list[ParsedCitation] = []
    seen: set[str] = set()
    for entry in payload.get("search_results", []) or []:
        url = entry.get("url")
        if url and url not in seen:
            seen.add(url)
            citations.append(ParsedCitation(url=url, title=entry.get("title", "")))
    # Fallback: older responses expose a bare `citations` URL list only.
    for url in payload.get("citations", []) or []:
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            citations.append(ParsedCitation(url=url))

    usage = payload.get("usage") or {}
    # Sonar always searched; count the searches it reports, else one.
    search_calls = usage.get("num_search_queries") or (1 if citations or text else 0)
    return ParsedResponse(
        text=text,
        citations=citations,
        web_search_calls=int(search_calls),
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        model=payload.get("model", ""),
    )


def parse_perplexity_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over either an Agent API body (`output[]`) or a legacy
    Sonar chat-completions body (`choices[]`); fixture-tested."""
    if "output" in payload:
        return _parse_agent_payload(payload)
    return _parse_legacy_payload(payload)


# See openai_api.ANSWER_MAX_TOKENS — the same methodology cap.
ANSWER_MAX_TOKENS = 1200


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str, web_search: bool = True,
    force_search: bool = True,
) -> dict[str, Any]:
    """Agent API body. The API rejects ANY unknown field with a 400, so only
    documented fields are sent."""
    body: dict[str, Any] = {
        "model": agent_model(model),
        "input": query_text.strip(),
        "max_output_tokens": ANSWER_MAX_TOKENS,
    }
    if persona_prompt.strip():  # no empty instructions for the baseline
        body["instructions"] = persona_prompt.strip()
    if web_search:
        # Search is NOT automatic on the Agent API. Forced by default so every
        # search variant is grounded (Sonar always searched — keeps the series
        # comparable); the natural probe offers the tool without forcing it.
        body["tools"] = [{"type": "web_search"}]
        if force_search:
            body["tool_choice"] = {"type": "web_search"}
    return body


def build_legacy_request_body(
    persona_prompt: str, query_text: str, *, model: str
) -> dict[str, Any]:
    messages = [{"role": "user", "content": query_text.strip()}]
    if persona_prompt.strip():  # no empty system message for the baseline
        messages.insert(0, {"role": "system", "content": persona_prompt.strip()})
    legacy_model = model.split("/", 1)[1] if model.startswith("perplexity/") else model
    return {
        "model": legacy_model or "sonar", "messages": messages,
        "max_tokens": ANSWER_MAX_TOKENS,
    }


async def _post_with_retries(
    client: httpx.AsyncClient, url: str, body: dict[str, Any], headers: dict[str, str],
    max_attempts: int,
) -> httpx.Response:
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.post(url, json=body, headers=headers)
        except httpx.TransportError:
            # Dropped connection / timeout: retry like a 5xx.
            if attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            raise
        if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
            await asyncio.sleep(2**attempt)
            continue
        if resp.status_code == 200:
            try:
                resp.json()
            except ValueError:
                # A 200 that isn't JSON (proxy/CDN error page): transient.
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
        return resp
    raise RuntimeError("unreachable")  # pragma: no cover


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    api_key: str,
    model: str,
    web_search: bool = True,
    force_search: bool = True,
    timeout_s: float = 90.0,
    max_attempts: int = 3,
) -> RetrievalOutcome:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        body = build_request_body(
            persona_prompt, query_text, model=model, web_search=web_search,
            force_search=force_search,
        )
        resp = await _post_with_retries(client, PERPLEXITY_AGENT_URL, body, headers, max_attempts)
        if resp.status_code in _FALLBACK_STATUS and web_search:
            # Agent API refused the request shape/model. Degrade to the legacy
            # endpoint (still answered via Perplexity's compatibility layer)
            # rather than losing the engine; tag the payload so it's visible.
            reason = f"agent_api_http_{resp.status_code}: {resp.text[:200]}"
            legacy = build_legacy_request_body(persona_prompt, query_text, model=model)
            resp = await _post_with_retries(client, PERPLEXITY_URL, legacy, headers, max_attempts)
            resp.raise_for_status()
            payload = resp.json()
            payload["_everpresent_fallback"] = reason
        else:
            resp.raise_for_status()
            payload = resp.json()
            status = payload.get("status")
            if status in ("failed", "cancelled"):
                # Agent API reports run failures as HTTP 200.
                err = payload.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"Perplexity run {status}: {msg or 'no detail'}")
        parsed = parse_perplexity_payload(payload)
        if not parsed.text:
            # Out of budget / empty run: an error, not "brand absent".
            reason = (payload.get("incomplete_details") or {}).get("reason", "no text")
            raise RuntimeError(f"Perplexity returned no answer text ({reason})")
        return RetrievalOutcome(
            payload=payload,
            parsed=parsed,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
