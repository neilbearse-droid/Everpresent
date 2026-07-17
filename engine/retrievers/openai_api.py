"""Mode A retriever: OpenAI Responses API with the web_search tool (§6.1).

The persona's prompt_text is the system prompt ("instructions"), the query is
the user turn — one call per (query × persona). Citations are read from
response.output[i].content[j].annotations; there is NO top-level `sources`
attribute (carried over from v1, §4).

This is a *measured surface*, not a utility LLM call: it exists because
clients want visibility on it, and it deliberately bypasses engine/llm's
allowlist router, which governs only the platform's own extraction models.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class ParsedCitation:
    url: str
    title: str = ""
    # The exact snippet the engine quoted from this source (§AEO-plan M6).
    # Claude exposes it (≤150 chars); other surfaces usually leave it empty.
    cited_text: str = ""

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.removeprefix("www.")


@dataclass
class ParsedResponse:
    text: str
    citations: list[ParsedCitation] = field(default_factory=list)
    web_search_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    # The sub-queries the engine actually issued on the way to this answer
    # (§AEO-plan M1 — query fan-out). Exposed by Gemini (webSearchQueries) and,
    # where present, OpenAI web_search_call actions. Empty when the surface
    # doesn't reveal it.
    fanout_queries: list[str] = field(default_factory=list)
    # Sources the engine consulted but did NOT cite in the answer (§AEO-plan
    # M6). A domain the engines read but skipped is competitive intel. Kept
    # separate from `citations` so citation counts stay clean.
    consulted_sources: list[ParsedCitation] = field(default_factory=list)


@dataclass
class RetrievalOutcome:
    payload: dict[str, Any]  # full raw Responses API body
    parsed: ParsedResponse
    latency_ms: int


def parse_responses_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Responses API body; fixture-tested, never network."""
    texts: list[str] = []
    citations: list[ParsedCitation] = []
    fanout_queries: list[str] = []
    web_search_calls = 0
    for item in payload.get("output") or []:
        item_type = item.get("type")
        if item_type == "web_search_call":
            web_search_calls += 1
            # The Responses API carries the issued query on the search action.
            query = (item.get("action") or {}).get("query")
            if query:
                fanout_queries.append(query)
            continue
        if item_type != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") != "output_text":
                continue
            texts.append(content.get("text", ""))
            for annotation in content.get("annotations") or []:
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    citations.append(
                        ParsedCitation(url=annotation["url"], title=annotation.get("title", ""))
                    )
    # Consulted-but-not-cited: the Responses API may return a fuller `sources`
    # list than the visible url_citations (§AEO-plan M6). Read it defensively —
    # absent on many responses — and exclude anything already cited.
    cited_urls = {c.url for c in citations}
    consulted: list[ParsedCitation] = []
    consulted_seen: set[str] = set()
    for src in payload.get("sources", []) or []:
        url = src.get("url") if isinstance(src, dict) else None
        if url and url not in cited_urls and url not in consulted_seen:
            consulted_seen.add(url)
            consulted.append(ParsedCitation(url=url, title=src.get("title", "")))

    usage = payload.get("usage") or {}
    return ParsedResponse(
        text="\n\n".join(t for t in texts if t),
        citations=citations,
        web_search_calls=web_search_calls,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=payload.get("model", ""),
        fanout_queries=fanout_queries,
        consulted_sources=consulted,
    )


# Consumer answers run a few hundred tokens; reasoning models bill their
# thinking as output. Capping output (and pinning low reasoning effort on
# GPT-5-class models) bounds cost without changing who gets cited — and
# matches the consumer app, which defaults to fast, low-reasoning replies.
# A methodology constant, not deployment config: comparability across runs
# requires every tenant to be measured the same way.
ANSWER_MAX_TOKENS = 1200


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str, web_search: bool = True,
    force_search: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "instructions": persona_prompt.strip(),
        "input": query_text,
        "max_output_tokens": ANSWER_MAX_TOKENS,
    }
    if model.startswith("gpt-5"):
        body["reasoning"] = {"effort": "low"}
    if web_search:
        # The search-DISABLED variant of the same call is the other half of
        # the dual-query diff the classifier consumes.
        body["tools"] = [{"type": "web_search"}]
        if force_search:
            # FORCE the search: given only the tool, gpt-4o often answers from
            # training and never searches, so the answer carries no url_citation
            # annotations. tool_choice makes the search variant reliably
            # retrieve — this is what yields ChatGPT citations, and matches the
            # consumer app (whose hidden system prompt pushes it to search).
            body["tool_choice"] = {"type": "web_search"}
        # else (§AEO-plan M2 natural probe): tool offered, `auto` tool_choice —
        # the model decides, so we can observe whether the prompt triggers
        # search at all.
    return body


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
    body = build_request_body(
        persona_prompt, query_text, model=model, web_search=web_search,
        force_search=force_search,
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            resp = await client.post(OPENAI_RESPONSES_URL, json=body, headers=headers)
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            payload = resp.json()
            return RetrievalOutcome(
                payload=payload,
                parsed=parse_responses_payload(payload),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    raise RuntimeError("unreachable")  # pragma: no cover
