"""Google AIO capture (§6.3): the SERP per query via Playwright
fresh-session with fixed per-tenant geolocation for reproducibility — AIO
block presence, cited sources, vertical position relative to organic, "Show
more" expansion, full rendered HTML to object storage.

Two providers behind one outcome shape:
- "direct": Playwright against google.com (primary). Datacenter IPs may hit
  consent walls or blocks; failures land as error results.
- "serpapi": the §6.3 fallback, a JSON API call — used when
  GOOGLE_AIO_PROVIDER=serpapi and SERPAPI_KEY is set.

No persona: a SERP takes no system prompt, so capture is per (query, geo),
one per query per run."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from engine.retrievers import google_aio_selectors as sel
from engine.retrievers.html_extract import extract_text_and_links
from engine.retrievers.openai_api import ParsedCitation

ADAPTER_VERSION = "v3.0.0"

_SKIP_HOST_FRAGMENTS = ("google.com", "google.ca", "gstatic.com", "googleusercontent.com")

SERPAPI_URL = "https://serpapi.com/search.json"


@dataclass
class AIOCaptureSummary:
    """The classifier's input (engine/processing/aio.py). Position index 0
    means the AIO block sits above the first organic result."""

    ran: bool = True
    aio_present: bool = False
    aio_position_index: int = -1
    aio_text_len: int = 0
    expanded: bool = False
    organic_count: int = 0


@dataclass
class AIOOutcome:
    summary: AIOCaptureSummary
    aio_text: str = ""
    aio_html: str = ""
    page_html: str = ""
    citations: list[ParsedCitation] = field(default_factory=list)
    latency_ms: int = 0


def parse_aio_fragment(html: str) -> tuple[str, list[ParsedCitation]]:
    """Text + outbound source links from a captured AIO block fragment."""
    return extract_text_and_links(html, _SKIP_HOST_FRAGMENTS)


def parse_serpapi_payload(payload: dict[str, Any]) -> AIOOutcome:
    """SerpAPI's google engine returns `ai_overview` when the SERP had one."""
    aio = payload.get("ai_overview") or {}
    text = "\n".join(
        block.get("snippet", "")
        for block in aio.get("text_blocks", [])
        if block.get("snippet")
    )
    citations = []
    seen: set[str] = set()
    for reference in aio.get("references", []):
        link = reference.get("link")
        if link and link not in seen:
            seen.add(link)
            citations.append(ParsedCitation(url=link, title=reference.get("title", "")))
    organic_count = len(payload.get("organic_results", []))
    present = bool(text or citations)
    summary = AIOCaptureSummary(
        aio_present=present,
        # SerpAPI surfaces the AIO as a top-of-page module when present.
        aio_position_index=0 if present else -1,
        aio_text_len=len(text),
        expanded=len(text) >= 1200,
        organic_count=organic_count,
    )
    return AIOOutcome(summary=summary, aio_text=text, citations=citations)


async def _capture_serpapi(
    query_text: str, *, gl: str, hl: str, api_key: str, timeout_s: float
) -> AIOOutcome:
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.get(
            SERPAPI_URL,
            params={"engine": "google", "q": query_text, "gl": gl, "hl": hl, "api_key": api_key},
        )
        resp.raise_for_status()
        outcome = parse_serpapi_payload(resp.json())
        outcome.page_html = ""  # JSON path has no rendered page
        outcome.latency_ms = int((time.monotonic() - started) * 1000)
        return outcome


async def _capture_direct(
    query_text: str,
    *,
    gl: str,
    hl: str,
    geolocation: dict[str, float] | None,
    headless: bool,
    timeout_s: float,
    executable_path: str | None,
) -> AIOOutcome:
    from playwright.async_api import async_playwright  # lazy: scrape worker only

    started = time.monotonic()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless, executable_path=executable_path or None
        )
        try:
            context_kwargs: dict[str, Any] = {"locale": hl}
            if geolocation:
                context_kwargs["geolocation"] = geolocation
                context_kwargs["permissions"] = ["geolocation"]
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
            await page.goto(
                f"{sel.SEARCH_URL}?q={query_text}&gl={gl}&hl={hl}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            for dismiss in sel.CONSENT_DISMISS_CANDIDATES:
                try:
                    await page.locator(dismiss).first.click(timeout=2_000)
                except Exception:  # noqa: BLE001 — consent walls are optional
                    pass
            await page.wait_for_selector(sel.ORGANIC_RESULT, timeout=30_000)

            aio_block = None
            for candidate in sel.AIO_BLOCK_CANDIDATES:
                locator = page.locator(candidate).first
                if await locator.count() > 0:
                    aio_block = locator
                    break
            if aio_block is None:
                heading = page.get_by_text(sel.AIO_HEADING_TEXT, exact=True).first
                if await heading.count() > 0:
                    aio_block = heading.locator(
                        "xpath=ancestor::div[@data-hveid or @jscontroller][1]"
                    )

            expanded = False
            aio_html = ""
            aio_text = ""
            citations: list[ParsedCitation] = []
            position_index = -1
            if aio_block is not None and await aio_block.count() > 0:
                try:
                    await page.locator(sel.SHOW_MORE_BUTTON).first.click(timeout=3_000)
                    expanded = True
                    await asyncio.sleep(1.0)
                except Exception:  # noqa: BLE001 — collapsed AIO is data too
                    pass
                aio_html = await aio_block.inner_html()
                aio_text, citations = parse_aio_fragment(aio_html)
                aio_box = await aio_block.bounding_box()
                first_organic = page.locator(sel.ORGANIC_RESULT).first
                organic_box = await first_organic.bounding_box()
                if aio_box and organic_box:
                    position_index = 0 if aio_box["y"] < organic_box["y"] else 1

            organic_count = await page.locator(sel.ORGANIC_RESULT).count()
            page_html = await page.content()
            await context.close()
            return AIOOutcome(
                summary=AIOCaptureSummary(
                    aio_present=bool(aio_html),
                    aio_position_index=position_index,
                    aio_text_len=len(aio_text),
                    expanded=expanded,
                    organic_count=organic_count,
                ),
                aio_text=aio_text,
                aio_html=aio_html,
                page_html=page_html,
                citations=citations,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            await browser.close()


async def capture(
    query_text: str,
    *,
    geo: dict[str, Any],
    provider: str = "direct",
    serpapi_key: str = "",
    headless: bool = True,
    timeout_s: float = 120.0,
    executable_path: str | None = None,
) -> AIOOutcome:
    gl = str(geo.get("gl", "ca"))
    hl = str(geo.get("hl", "en"))
    geolocation = None
    if "lat" in geo and "lng" in geo:
        geolocation = {"latitude": float(geo["lat"]), "longitude": float(geo["lng"])}
    if provider == "serpapi" and serpapi_key:
        return await _capture_serpapi(
            query_text, gl=gl, hl=hl, api_key=serpapi_key, timeout_s=timeout_s
        )
    return await _capture_direct(
        query_text,
        gl=gl,
        hl=hl,
        geolocation=geolocation,
        headless=headless,
        timeout_s=timeout_s,
        executable_path=executable_path,
    )
