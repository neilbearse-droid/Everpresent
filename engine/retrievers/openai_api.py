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


@dataclass
class RetrievalOutcome:
    payload: dict[str, Any]  # full raw Responses API body
    parsed: ParsedResponse
    latency_ms: int


def parse_responses_payload(payload: dict[str, Any]) -> ParsedResponse:
    """Pure parser over a Responses API body; fixture-tested, never network."""
    texts: list[str] = []
    citations: list[ParsedCitation] = []
    web_search_calls = 0
    for item in payload.get("output", []):
        item_type = item.get("type")
        if item_type == "web_search_call":
            web_search_calls += 1
            continue
        if item_type != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") != "output_text":
                continue
            texts.append(content.get("text", ""))
            for annotation in content.get("annotations", []):
                if annotation.get("type") == "url_citation" and annotation.get("url"):
                    citations.append(
                        ParsedCitation(url=annotation["url"], title=annotation.get("title", ""))
                    )
    usage = payload.get("usage", {})
    return ParsedResponse(
        text="\n\n".join(t for t in texts if t),
        citations=citations,
        web_search_calls=web_search_calls,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=payload.get("model", ""),
    )


def build_request_body(
    persona_prompt: str, query_text: str, *, model: str, web_search: bool = True
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "instructions": persona_prompt.strip(),
        "input": query_text,
    }
    if web_search:
        # The search-DISABLED variant of the same call is the other half of
        # the dual-query diff the classifier consumes (arrives M3).
        body["tools"] = [{"type": "web_search"}]
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
