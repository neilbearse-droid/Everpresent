"""On-page presence audit + citability fingerprint (§focus-group #2/#3).

For each Power Page (a URL the engines cite for the tenant's queries), fetch
the page and answer two questions the strategist actually asks:
- is the brand (or a competitor) actually NAMED on this page?
- does the page carry the structural features that cited pages share
  (structured data, FAQ schema, tables, recent dates)?

Pure detection/extraction logic is separated from fetching so it stays
fixture-tested; only crawl_page touches the network. Name matching reuses the
mention detector's word-boundary rule so "on-page presence" and "in-answer
presence" agree on what counts as a mention.
"""

import re
from typing import Any

import httpx

from engine.processing.mentions import _first_match
from engine.retrievers.html_extract import extract_text_and_links

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MAX_HTML_BYTES = 1_500_000  # a cited article, not a tarpit
_RECENT_YEARS = ("2024", "2025", "2026")


def detect_presence(
    html: str,
    brand_names: list[str],
    competitors: list[tuple[str, list[str]]],
) -> dict[str, Any]:
    """Word-boundary presence of the brand (any alias) and each competitor
    (name or alias) in the page's visible text."""
    text, _links = extract_text_and_links(html, ())
    text_lower = text.lower()
    brand_found = any(
        _first_match(text_lower, alias) >= 0 for alias in brand_names if alias
    )
    competitors_found = sorted(
        name
        for name, aliases in competitors
        if any(_first_match(text_lower, a) >= 0 for a in [name, *aliases] if a)
    )
    return {"brand_found": brand_found, "competitors_found": competitors_found}


def extract_features(html: str) -> dict[str, Any]:
    """Cheap citability fingerprint. These are the structural features that
    keep showing up on pages engines cite: machine-readable structure
    (JSON-LD, FAQ schema), comparison tables, and recent dates."""
    lower = html.lower()
    text, _ = extract_text_and_links(html, ())
    return {
        "json_ld": "application/ld+json" in lower,
        "faq_schema": "faqpage" in lower,
        "has_tables": "<table" in lower,
        "recent_year_mentions": sum(len(re.findall(y, text)) for y in _RECENT_YEARS),
        "word_count": len(text.split()),
    }


def crawl_page(client: httpx.Client, url: str) -> dict[str, Any]:
    """Fetch one page. Returns {html, http_status} or {error}."""
    try:
        resp = client.get(url, headers={"User-Agent": BROWSER_UA})
        html = resp.text[:MAX_HTML_BYTES]
        return {"html": html, "http_status": resp.status_code}
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "http_status": None}
