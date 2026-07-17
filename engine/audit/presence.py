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

# --- Tier-1 citability signals (§AEO-plan M5) ------------------------------
# The peer-reviewed GEO study (Aggarwal et al., KDD 2024) + Semrush/Indig data
# rank these as the levers that actually move citation, well above schema:
# quotations (~41%), statistics/data density (~30-40%), an answer capsule under
# a question heading, front-loading, cited sources — and promotional tone is
# penalized (~-26%).

# Currency, percentages, scaled numbers, and any multi-digit figure — a proxy
# for "data-rich" (pages with 19+ data points earn 2-3x citations).
_STAT_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"
    r"|\d+(?:\.\d+)?\s?%"
    r"|\b\d+(?:\.\d+)?\s?(?:percent|million|billion|thousand|bps|x|×)\b"
    r"|\b\d{2,}\b",
    re.IGNORECASE,
)
# Attributed quotations: a blockquote, or a quote-delimited span of real length.
_BLOCKQUOTE_RE = re.compile(r"<blockquote", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"“][^\"“”]{30,}[\"”]")
_HREF_RE = re.compile(r'href=["\'](https?://[^"\'#?]+)', re.IGNORECASE)
# Marketing voice AI engines are "allergic" to — measured as a rate, higher=worse.
_PROMO_PHRASES = (
    "best-in-class", "best in class", "world-class", "world class", "cutting-edge",
    "cutting edge", "industry-leading", "industry leading", "revolutionary",
    "game-changer", "game changer", "seamless", "unlock", "empower", "leverage",
    "state-of-the-art", "state of the art", "unparalleled", "premier", "one-stop",
    "look no further", "trusted by", "next-generation", "next generation",
    "supercharge", "effortless", "unrivaled", "unrivalled", "revolutionize",
)


def _host(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].lower()


_HEADING_RE = re.compile(r"<h[1-4][^>]*>(.*?)</h[1-4]>", re.IGNORECASE | re.DOTALL)
_PARA_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _has_answer_capsule(html: str) -> bool:
    """A ~40-60 word direct answer immediately under a question-format heading —
    72% of cited blog posts have one. Detected on HTML structure (robust to
    source line-wrapping): a question heading followed by a paragraph of
    answer-capsule length."""
    for m in _HEADING_RE.finditer(html):
        heading = _TAG_RE.sub("", m.group(1)).strip()
        if heading.endswith("?") and len(heading.split()) <= 20:
            after = _PARA_RE.search(html[m.end():])
            if after:
                words = len(_TAG_RE.sub(" ", after.group(1)).split())
                if 25 <= words <= 120:
                    return True
    return False


def _front_loaded(text: str) -> bool:
    """Does substance (a statistic) appear in the first 30% of the page? 44% of
    ChatGPT citations come from the first third."""
    if len(text.split()) < 60:
        return False
    head = text[: int(len(text) * 0.3)]
    return bool(_STAT_RE.search(head))


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
    """Citability fingerprint. Two layers: the Tier-1 evidence-based levers that
    actually move citation (quotations, statistics/data density, an answer
    capsule, front-loading, cited sources; promotional tone is a penalty), and
    the machine-legibility *hygiene* signals (JSON-LD, FAQ schema, tables,
    recency) — useful for entity disambiguation, but not citation levers."""
    lower = html.lower()
    text, _ = extract_text_and_links(html, ())
    word_count = len(text.split())

    statistic_count = sum(1 for _ in _STAT_RE.finditer(text))
    quotation_count = len(_BLOCKQUOTE_RE.findall(html)) + len(_QUOTE_RE.findall(text))
    citation_count = len({_host(u) for u in _HREF_RE.findall(html)})
    promo_hits = sum(lower.count(p) for p in _PROMO_PHRASES)
    promotional_tone_score = round(1000.0 * promo_hits / max(word_count, 1), 1)

    return {
        # Tier-1 levers (evidence-based).
        "quotation_count": quotation_count,
        "statistic_count": statistic_count,
        "data_point_density": round(statistic_count / max(word_count, 1), 4),
        "has_answer_capsule": _has_answer_capsule(html),
        "front_loaded": _front_loaded(text),
        "citation_count": citation_count,
        "promotional_tone_score": promotional_tone_score,
        # Hygiene signals (entity legibility, not citation levers).
        "json_ld": "application/ld+json" in lower,
        "faq_schema": "faqpage" in lower,
        "has_tables": "<table" in lower,
        "recent_year_mentions": sum(len(re.findall(y, text)) for y in _RECENT_YEARS),
        "word_count": word_count,
    }


def crawl_page(client: httpx.Client, url: str) -> dict[str, Any]:
    """Fetch one page. Returns {html, http_status} or {error}."""
    try:
        resp = client.get(url, headers={"User-Agent": BROWSER_UA})
        html = resp.text[:MAX_HTML_BYTES]
        return {"html": html, "http_status": resp.status_code}
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "http_status": None}
