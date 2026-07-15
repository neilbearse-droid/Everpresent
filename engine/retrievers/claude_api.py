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
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _collect_citations(payload: dict[str, Any]) -> list[ParsedCitation]:
    citations: list[ParsedCitation] = []
    seen: set[str] = set()

    def add(url: str | None, title: str = "") -> None:
        if url and url not in seen:
            seen.add(url)
            citations.append(ParsedCitation(url=url, title=title or ""))

    for block in payload.get("content", []):
        btype = block.get("type")
        if btype == "text":
            for cite in block.get("citations", []) or []:
                add(cite.get("url"), cite.get("title", ""))
        elif btype == "web_search_tool_result":
            content = block.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "web_search_result":
                        add(item.get("url"), item.get("title", ""))
    return citations


def parse_claude_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Messages API body; fixture-tested, never network."""
    texts = [
        block.get("text", "")
        for block in payload.get("content", [])
        if block.get("type") == "text"
    ]
    usage = payload.get("usage", {})
    server_tool = usage.get("server_tool_use", {}) or {}
    return ParsedResponse(
        text="\n\n".join(t for t in texts if t),
        citations=_collect_citations(payload),
        web_search_calls=int(server_tool.get("web_search_requests", 0)),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=payload.get("model", ""),
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
