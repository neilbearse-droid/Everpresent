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
from urllib.parse import quote_plus

import httpx

from engine.retrievers import google_aio_selectors as sel
from engine.retrievers.blocking import assert_not_blocked
from engine.retrievers.html_extract import extract_text_and_links
from engine.retrievers.openai_api import ParsedCitation
from engine.retrievers.stealth import ScrapeEnv, browser_page

ADAPTER_VERSION = "v3.1.0"

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


def _serpapi_block_text(block: dict[str, Any]) -> str:
    """Snippet text of one AIO text-block, including nested list/table items
    (SerpApi puts list content under a `list` of sub-blocks, not `snippet`)."""
    if block.get("snippet"):
        return str(block["snippet"])
    nested = block.get("list") or block.get("text_blocks") or []
    return "\n".join(_serpapi_block_text(b) for b in nested if isinstance(b, dict))


def parse_serpapi_payload(payload: dict[str, Any]) -> AIOOutcome:
    """SerpAPI's google engine returns `ai_overview` when the SERP had one."""
    aio = payload.get("ai_overview") or {}
    text = "\n".join(
        t for t in (_serpapi_block_text(b) for b in (aio.get("text_blocks") or [])) if t
    )
    citations = []
    seen: set[str] = set()
    for reference in aio.get("references") or []:
        link = reference.get("link")
        if link and link not in seen:
            seen.add(link)
            citations.append(ParsedCitation(url=link, title=reference.get("title", "")))
    organic_count = len(payload.get("organic_results") or [])
    # An AIO that requires a second fetch comes back as just a `page_token`
    # with no inline blocks. It still MEANS an AIO appeared — treat it as
    # present (not a false "no AIO") even though we don't expand it here.
    has_page_token = bool(aio.get("page_token"))
    present = bool(text or citations or has_page_token)
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
    env: ScrapeEnv | None = None,
) -> AIOOutcome:
    scrape_env = env or ScrapeEnv(
        headless=headless,
        executable_path=executable_path,
        country=gl,
        language=hl,
        latitude=geolocation["latitude"] if geolocation else None,
        longitude=geolocation["longitude"] if geolocation else None,
    )

    started = time.monotonic()
    async with browser_page(scrape_env) as (_browser, _context, page):
        await page.goto(
            f"{sel.SEARCH_URL}?q={quote_plus(query_text)}&gl={gl}&hl={hl}",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        # Google's "unusual traffic" wall is the single likeliest block; catch
        # it before waiting for organic results that will never render.
        await assert_not_blocked(page)
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
                # Scope the "Show more" click to the AIO block: a page-wide
                # .first can click another module's expander (e.g. "People also
                # ask"), falsely setting expanded=True (§audit low).
                await aio_block.locator(sel.SHOW_MORE_BUTTON).first.click(timeout=3_000)
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
            else:
                # Geometry unavailable (element not laid out in headless): a
                # present AIO defaults to top-of-page, matching the serpapi
                # contract, instead of staying -1 → misclassified organic-first
                # (§audit low).
                position_index = 0

        organic_count = await page.locator(sel.ORGANIC_RESULT).count()
        page_html = await page.content()
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


async def capture(
    query_text: str,
    *,
    geo: dict[str, Any],
    provider: str = "direct",
    serpapi_key: str = "",
    headless: bool = True,
    timeout_s: float = 120.0,
    executable_path: str | None = None,
    env: ScrapeEnv | None = None,
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
    # When an env is supplied (proxy/stealth from Settings), keep the request's
    # geo authoritative over whatever the caller pre-filled.
    if env is not None:
        env.country = gl
        env.language = hl
        if geolocation:
            env.latitude = geolocation["latitude"]
            env.longitude = geolocation["longitude"]
    return await _capture_direct(
        query_text,
        gl=gl,
        hl=hl,
        geolocation=geolocation,
        headless=headless,
        timeout_s=timeout_s,
        executable_path=executable_path,
        env=env,
    )
