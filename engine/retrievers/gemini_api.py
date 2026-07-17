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

import httpx

from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def parse_gemini_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a generateContent body; fixture-tested, never network."""
    candidates = payload.get("candidates", [])
    text = ""
    citations: list[ParsedCitation] = []
    web_search_calls = 0
    if candidates:
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "\n\n".join(p.get("text", "") for p in parts if p.get("text"))

        grounding = first.get("groundingMetadata", {}) or {}
        seen: set[str] = set()
        for chunk in grounding.get("groundingChunks", []) or []:
            web = chunk.get("web", {}) or {}
            url = web.get("uri")
            if url and url not in seen:
                seen.add(url)
                citations.append(ParsedCitation(url=url, title=web.get("title", "")))
        queries = grounding.get("webSearchQueries", []) or []
        web_search_calls = len(queries) if queries else (1 if citations else 0)

    usage = payload.get("usageMetadata", {})
    return ParsedResponse(
        text=text,
        citations=citations,
        web_search_calls=web_search_calls,
        input_tokens=usage.get("promptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0),
        model=payload.get("modelVersion", ""),
    )


# See openai_api.ANSWER_MAX_TOKENS — the same methodology cap. Gemini bills
# "thinking" as output tokens; Flash models accept thinkingBudget 0, which we
# set (matching the consumer product's fast path). Pro models don't allow
# disabling thinking, so they get only the output cap.
ANSWER_MAX_TOKENS = 1200


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str = "", web_search: bool = True
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {"maxOutputTokens": ANSWER_MAX_TOKENS}
    if "flash" in model:
        generation_config["thinkingConfig"] = {"thinkingBudget": 0}
    body: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": persona_prompt.strip()}]},
        "contents": [{"role": "user", "parts": [{"text": query_text.strip()}]}],
        "generationConfig": generation_config,
    }
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
    timeout_s: float = 90.0,
    max_attempts: int = 3,
) -> RetrievalOutcome:
    body = build_request_body(persona_prompt, query_text, model=model, web_search=web_search)
    url = f"{GEMINI_BASE}/{model}:generateContent"
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            resp = await client.post(
                url, json=body, headers={"x-goog-api-key": api_key}
            )
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            return RetrievalOutcome(
                payload=payload,
                parsed=parse_gemini_payload(payload),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
