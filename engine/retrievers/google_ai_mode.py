"""Mode B retriever: Google AI Mode via SerpApi (`engine=google_ai_mode`).

AI Mode is Google's conversational search tab (1B+ monthly users by I/O 2026)
and it cites different pages than AI Overviews (~14% URL overlap for the same
query, per Ahrefs), so AI Overviews data can't stand in for it. There is no
official API for its answers; SerpApi returns the rendered answer as
`text_blocks` (with `reference_indexes` into `references`).

Like Google AI Overviews, a SERP takes no persona: one capture per
(query, location). Reuses google_aio's retrying SerpApi client so transient
429/5xx/non-JSON responses don't cost a data point.

Legal note: Google's suit against SerpApi was unresolved as of Sept 2026.
Keep this behind the provider abstraction so a second vendor (DataForSEO,
Bright Data) can be swapped in.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.processing.ads import sponsored_from_serp
from engine.retrievers.google_aio import _serpapi_block_text, _serpapi_get
from engine.retrievers.openai_api import ParsedCitation

ADAPTER_VERSION = "google-ai-mode-serpapi-v1"


@dataclass
class AIModeOutcome:
    text: str
    citations: list[ParsedCitation] = field(default_factory=list)
    html_fragment: str = ""  # JSON path: no rendered page
    latency_ms: int = 0
    shopping_results: int = 0
    present: bool = False
    # Paid units SerpApi reports alongside the answer (kept out of `text`).
    sponsored: list[dict[str, str]] = field(default_factory=list)


def parse_ai_mode_payload(payload: dict[str, Any]) -> AIModeOutcome:
    """Pure parser over SerpApi's google_ai_mode response; fixture-tested."""
    blocks = payload.get("text_blocks") or []
    text = "\n".join(t for t in (_serpapi_block_text(b) for b in blocks) if t)
    # Some responses carry a pre-rendered markdown answer; prefer blocks.
    if not text:
        text = str(payload.get("reconstructed_markdown") or "").strip()
    citations: list[ParsedCitation] = []
    seen: set[str] = set()
    for ref in payload.get("references") or []:
        if not isinstance(ref, dict):
            continue
        link = ref.get("link")
        if isinstance(link, str) and link and link not in seen:
            seen.add(link)
            citations.append(ParsedCitation(url=link, title=str(ref.get("title") or "")))
    return AIModeOutcome(
        text=text,
        citations=citations,
        shopping_results=len(payload.get("shopping_results") or []),
        present=bool(text or citations),
        sponsored=[u.as_dict() for u in sponsored_from_serp(payload)],
    )


async def capture(
    query_text: str, *, geo: dict, api_key: str, timeout_s: float = 120.0
) -> AIModeOutcome:
    if not api_key:
        raise RuntimeError("SERPAPI_KEY is not set on the worker")
    started = time.monotonic()
    params = {
        "engine": "google_ai_mode",
        "q": query_text,
        "gl": str(geo.get("gl") or "us"),
        "hl": str(geo.get("hl") or "en"),
        "api_key": api_key,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        payload = await _serpapi_get(client, params)
    if payload.get("error"):
        # SerpApi reports some failures in-body with HTTP 200.
        raise RuntimeError(f"SerpApi AI Mode error: {str(payload['error'])[:200]}")
    outcome = parse_ai_mode_payload(payload)
    if not outcome.present:
        # AI Mode always answers; an empty capture is a failed capture, not
        # "brand absent".
        raise RuntimeError("AI Mode capture returned no answer")
    outcome.latency_ms = int((time.monotonic() - started) * 1000)
    return outcome
