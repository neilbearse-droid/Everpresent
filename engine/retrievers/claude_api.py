"""Mode A retriever: Anthropic Claude Messages API with the server-side web
search tool (§6.1).

The persona prompt is the `system` field, the query is the user turn. Citations
are read from two places and deduped: the `citations` array on text blocks
(web_search_result_location) and the `web_search_tool_result` blocks. Web
search counts come from usage.server_tool_use.web_search_requests.

Measured surface: this is what a claude.ai consumer sees, called directly. The
configured model is a real consumer model, never a build-time (fable/mythos)
model — the policy test (§4) scans config for that. It deliberately bypasses
engine/llm's allowlist router, which governs only the platform's own utility
models.
"""

import asyncio
import time
from typing import Any

import httpx

from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# max_uses 3: web search bills per search performed ($10/1k); consumer-style
# queries rarely need more, so this caps the fee tail without changing the
# answer for the typical case.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _collect_citations(
    payload: dict[str, Any],
) -> tuple[list[ParsedCitation], list[ParsedCitation]]:
    """Claude distinguishes the two naturally (§AEO-plan M6): text-block
    `citations` are what the answer actually referenced (they carry the quoted
    `cited_text`), while `web_search_tool_result` blocks are everything search
    surfaced. Cited = the former; consulted = search results the answer didn't
    reference."""
    cited: list[ParsedCitation] = []
    cited_seen: set[str] = set()
    for block in payload.get("content", []):
        if block.get("type") != "text":
            continue
        for cite in block.get("citations", []) or []:
            url = cite.get("url")
            if url and url not in cited_seen:
                cited_seen.add(url)
                cited.append(ParsedCitation(
                    url=url,
                    title=cite.get("title", "") or "",
                    cited_text=(cite.get("cited_text", "") or "")[:150],
                ))

    consulted: list[ParsedCitation] = []
    consulted_seen: set[str] = set()
    for block in payload.get("content", []):
        if block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if item.get("type") != "web_search_result":
                continue
            url = item.get("url")
            if url and url not in cited_seen and url not in consulted_seen:
                consulted_seen.add(url)
                consulted.append(ParsedCitation(url=url, title=item.get("title", "") or ""))
    return cited, consulted


def parse_claude_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Messages API body; fixture-tested, never network."""
    texts = [
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ]
    usage = payload.get("usage", {})
    server_tool = usage.get("server_tool_use", {}) or {}
    cited, consulted = _collect_citations(payload)
    return ParsedResponse(
        text="\n\n".join(t for t in texts if t),
        citations=cited,
        web_search_calls=int(server_tool.get("web_search_requests", 0)),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=payload.get("model", ""),
        consulted_sources=consulted,
    )


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str, web_search: bool = True
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": 1024,
        "system": persona_prompt.strip(),
        "messages": [{"role": "user", "content": query_text.strip()}],
    }
    if web_search:
        # The search-DISABLED twin is the other half of the dual-query diff.
        body["tools"] = [WEB_SEARCH_TOOL]
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
    body = build_request_body(persona_prompt, query_text, model=model, web_search=web_search)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            resp = await client.post(ANTHROPIC_URL, json=body, headers=headers)
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            return RetrievalOutcome(
                payload=payload,
                parsed=parse_claude_payload(payload),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
