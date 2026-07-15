"""Mode A retriever: Perplexity Sonar API (§6.1).

Sonar is an answer engine — every call is web-grounded, so there is no
search-disabled twin (Perplexity has no non-search mode). The persona prompt is
the system message, the query is the user turn. Citations come from the
top-level `search_results` (preferred, they carry titles) or `citations`
(bare URLs).

Like openai_api, this is a *measured surface*: it calls the provider directly
and deliberately bypasses engine/llm's allowlist router, which governs only the
platform's own extraction models.
"""

import asyncio
import time
from typing import Any

import httpx

from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def parse_perplexity_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Sonar (OpenAI-compatible) chat body; fixture-tested."""
    choices = payload.get("choices", [])
    text = ""
    if choices:
        text = choices[0].get("message", {}).get("content", "") or ""

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

    usage = payload.get("usage", {})
    # Sonar always searches; count the searches it reports, else one.
    search_calls = usage.get("num_search_queries") or (1 if citations or text else 0)
    return ParsedResponse(
        text=text,
        citations=citations,
        web_search_calls=int(search_calls),
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        model=payload.get("model", ""),
    )


def build_request_body(persona_prompt: str, query_text: str, *, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": persona_prompt.strip()},
            {"role": "user", "content": query_text.strip()},
        ],
    }


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    api_key: str,
    model: str,
    web_search: bool = True,  # accepted for a uniform adapter interface; Sonar always searches
    timeout_s: float = 90.0,
    max_attempts: int = 3,
) -> RetrievalOutcome:
    body = build_request_body(persona_prompt, query_text, model=model)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            resp = await client.post(PERPLEXITY_URL, json=body, headers=headers)
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            return RetrievalOutcome(
                payload=payload,
                parsed=parse_perplexity_payload(payload),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
