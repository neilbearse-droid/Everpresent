"""Mode A retriever: Meta AI through the Meta Model API (Muse Spark).

Muse Spark has answered in the Meta AI app, on meta.ai and in the search bars
of Facebook, Instagram, WhatsApp and Messenger since April 2026. The Model
API serves the same model family with the OpenAI-style Responses API
(`api.meta.ai/v1/responses`) and a built-in `web_search` tool whose answers
carry `url_citation` annotations, so the OpenAI parser reads them unchanged.

The search is offered, not forced: the Meta AI app decides for itself when to
search, and `tool_choice` support on this API is undocumented. Like Claude
and Gemini, the measured answer is therefore already what users get.

What this can't see: the app can also search Instagram, Threads and Facebook
posts and product catalogs, and the Muse shopping agent acts inside WhatsApp.
Neither is reachable through the API, so this measures the model with web
search, not the app.
"""

import asyncio
import time
from typing import Any

import httpx

from engine.retrievers.openai_api import (
    RETRYABLE_STATUS,
    ParsedResponse,
    RetrievalOutcome,
    _error_message,
    _retry_after,
    parse_responses_payload,
)

META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
ADAPTER_VERSION = "meta-responses-v1"
# Same cap as the other API engines, for the same reason (bounded cost,
# consumer-length answers, comparable across engines).
ANSWER_MAX_TOKENS = 1200
# Muse Spark always reasons (no "none"), the API defaults to medium or higher,
# and reasoning tokens come out of max_output_tokens before any answer text.
# Unpinned, a 1,200-token cap can end in a cut-off or empty answer. Low also
# matches the app, whose default Instant mode is the fast, light one; Thinking
# is opt-in. Same pin as the OpenAI adapter (DECISIONS M53).
REASONING_EFFORT = "low"


def parse_meta_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Responses API body from Meta; fixture-tested."""
    parsed = parse_responses_payload(payload)
    if not parsed.web_search_calls and parsed.citations:
        # A cited answer searched, whether or not the body lists the search
        # step. Counting it keeps "searched the web" and the search fee honest.
        parsed.web_search_calls = 1
    return parsed


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str, web_search: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "input": query_text,
        "max_output_tokens": ANSWER_MAX_TOKENS,
        "reasoning": {"effort": REASONING_EFFORT},
    }
    if persona_prompt.strip():
        body["instructions"] = persona_prompt.strip()
    if web_search:
        body["tools"] = [{"type": "web_search"}]
    return body


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    api_key: str,
    model: str,
    web_search: bool = True,
    force_search: bool = True,  # §AEO-plan M2: honored only by OpenAI and Perplexity
    timeout_s: float = 90.0,
    max_attempts: int = 3,
) -> RetrievalOutcome:
    body = build_request_body(persona_prompt, query_text, model=model, web_search=web_search)
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.post(META_RESPONSES_URL, json=body, headers=headers)
            except httpx.TransportError:
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(_retry_after(resp) or 2**attempt)
                continue
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"Meta {resp.status_code}: {_error_message(resp)}",
                    request=resp.request, response=resp,
                )
            try:
                payload = resp.json()
            except ValueError:
                if attempt < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                raise
            parsed = parse_meta_payload(payload)
            if not parsed.text:
                # No answer text is an error, never an answer that "doesn't
                # mention the brand".
                reason = (payload.get("incomplete_details") or {}).get("reason") \
                    or payload.get("status") or "unknown"
                raise RuntimeError(f"Meta returned no answer text ({reason})")
            return RetrievalOutcome(
                payload=payload,
                parsed=parsed,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
