"""Mode A retriever: Google Gemini API with Google Search grounding (§6.1).

The persona prompt is the system instruction, the query is the user turn.
Grounding citations come from candidates[0].groundingMetadata.groundingChunks[].web.
The API key is a URL query parameter, not a header.

Measured surface: what a Gemini consumer sees, called directly. It deliberately
bypasses engine/llm's allowlist router, which governs only the platform's own
utility models.
"""

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# 529 is Anthropic's "overloaded"; common under load, always transient.
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


_REDIRECT_HOST = "vertexaisearch.cloud.google.com"


def _grounding_domain(url: str, title: str) -> str:
    """Gemini grounding URIs are Google redirects; the chunk title carries the
    real source domain (e.g. "godaddy.com"). Use it when the URI is a
    redirect and the title looks like a bare domain; otherwise leave the
    domain to be parsed from the URL."""
    host = (urlparse(url).hostname or "").lower()
    candidate = title.strip().lower()
    if (
        (host == _REDIRECT_HOST or "grounding-api-redirect" in url)
        and "." in candidate
        and " " not in candidate
        and "/" not in candidate
    ):
        return candidate.removeprefix("www.")
    return ""


def parse_gemini_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a generateContent body; fixture-tested, never network."""
    candidates = payload.get("candidates") or []
    text = ""
    citations: list[ParsedCitation] = []
    web_search_calls = 0
    if candidates:
        first = candidates[0]
        parts = (first.get("content") or {}).get("parts") or []
        text = "\n\n".join(p.get("text", "") for p in parts if p.get("text"))

        grounding = first.get("groundingMetadata", {}) or {}
        seen: set[str] = set()
        for chunk in grounding.get("groundingChunks", []) or []:
            web = chunk.get("web", {}) or {}
            url = web.get("uri")
            if url and url not in seen:
                seen.add(url)
                title = str(web.get("title", "") or "")
                citations.append(ParsedCitation(
                    url=url, title=title, source_domain=_grounding_domain(url, title)
                ))
        queries = list(grounding.get("webSearchQueries", []) or [])
        web_search_calls = len(queries) if queries else (1 if citations else 0)

    usage = payload.get("usageMetadata") or {}
    return ParsedResponse(
        text=text,
        citations=citations,
        web_search_calls=web_search_calls,
        input_tokens=usage.get("promptTokenCount", 0),
        # Thinking tokens are billed as output but reported separately.
        output_tokens=usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
        model=payload.get("modelVersion", ""),
        # Gemini is the richest fan-out source: the exact sub-queries it ran.
        fanout_queries=queries if candidates else [],
    )


# See openai_api.ANSWER_MAX_TOKENS — the same methodology cap. Gemini bills
# "thinking" as output tokens; Flash models accept thinkingBudget 0, which we
# set (matching the consumer product's fast path). Pro models don't allow
# disabling thinking, so they get only the output cap.
ANSWER_MAX_TOKENS = 1200
PRO_THINKING_BUDGET = 128  # the minimum Pro accepts
PRO_THINKING_HEADROOM = 1024
# Stable model a retired/unknown configured model falls back to (2.5 Pro was
# deprecated for 2026-10-16 and refuses new users; Gemini 4 isn't GA yet).
FALLBACK_MODEL = "gemini-3.6-flash"
# Gemini 3 replaces thinkingBudget with thinkingLevel (sending both is an
# error). "low" matches the consumer app's fast path, like OpenAI effort=low.
GEMINI3_THINKING_LEVEL = "low"
_MODEL_GONE_STATUS = {400, 404}


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str = "", web_search: bool = True
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {"maxOutputTokens": ANSWER_MAX_TOKENS}
    if model.startswith("gemini-3") or model.startswith("gemini-4"):
        # Thinking can't be fully disabled on Gemini 3 and counts toward
        # maxOutputTokens, so keep it low and leave headroom for it.
        generation_config["thinkingConfig"] = {"thinkingLevel": GEMINI3_THINKING_LEVEL}
        generation_config["maxOutputTokens"] = ANSWER_MAX_TOKENS + PRO_THINKING_HEADROOM
    elif "2.5-flash" in model:
        # 2.5 Flash / Flash-Lite can turn thinking off (2.0 models have no
        # thinkingConfig at all and would reject it).
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    elif "pro" in model:
        # Pro can't disable thinking and thinking counts toward
        # maxOutputTokens, so pin the minimum budget and leave headroom —
        # otherwise answers come back empty with finishReason MAX_TOKENS.
        generation_config["thinkingConfig"] = {"thinkingBudget": PRO_THINKING_BUDGET}
        generation_config["maxOutputTokens"] = ANSWER_MAX_TOKENS + PRO_THINKING_HEADROOM
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": query_text.strip()}]}],
        "generationConfig": generation_config,
    }
    # Gemini rejects an empty text part; the generic baseline persona has no
    # prompt, so omit the system instruction entirely in that case.
    if persona_prompt.strip():
        body["system_instruction"] = {"parts": [{"text": persona_prompt.strip()}]}
    if web_search:
        # The grounding-DISABLED twin is the other half of the dual-query diff.
        body["tools"] = [{"google_search": {}}]
    return body


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    api_key: str,
    model: str,
    web_search: bool = True,
    force_search: bool = True,  # §AEO-plan M2: honored only by OpenAI
    timeout_s: float = 90.0,
    max_attempts: int = 3,
) -> RetrievalOutcome:
    started = time.monotonic()
    fallback_reason = ""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 2):
            body = build_request_body(
                persona_prompt, query_text, model=model, web_search=web_search
            )
            url = f"{GEMINI_BASE}/{model}:generateContent"
            try:
                resp = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
            except httpx.TransportError:
                # Dropped connection / timeout: retry like a 5xx.
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            if (
                resp.status_code in _MODEL_GONE_STATUS
                and model != FALLBACK_MODEL
                and not fallback_reason
                and "model" in resp.text.lower()
            ):
                # Configured model retired / not available to this project:
                # degrade to the stable model once instead of losing the engine.
                fallback_reason = f"{model}: HTTP {resp.status_code}: {resp.text[:160]}"
                model = FALLBACK_MODEL
                continue
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError:
                # A 200 that isn't JSON (proxy/CDN error page): transient.
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
            candidates = payload.get("candidates") or []
            if candidates and not parse_gemini_payload(payload).text:
                # e.g. finishReason MAX_TOKENS/SAFETY with no text: an error,
                # not an answer that "doesn't mention the brand".
                reason = candidates[0].get("finishReason", "unknown")
                raise RuntimeError(f"Gemini returned no answer text ({reason})")
            if fallback_reason:
                payload["_everpresent_model_fallback"] = fallback_reason
            return RetrievalOutcome(
                payload=payload,
                parsed=parse_gemini_payload(payload),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
