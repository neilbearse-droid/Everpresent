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
from datetime import UTC, datetime
from typing import Any

import httpx

from engine.processing.mentions import _first_match
from engine.retrievers.html_extract import extract_text_and_links

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MAX_HTML_BYTES = 1_500_000  # a cited article, not a tarpit
# --- Citability signals, ranked by the 2026 evidence ------------------------
# Controlled 2026 studies (252k-trial factorial test, arXiv 2605.25517; the
# CITECHOICE causal replay, 2609.15164) agree: a page must be RETRIEVED first
# (topical match to the sub-queries engines run), then EXPLICIT FACTS — prices,
# recent dates, ratings — raise citation odds, and evidence density (numbers,
# definitions, comparisons, steps) decides how much of the page the answer
# uses. Formatting (answer capsules, front-loading, schema) only shifts credit
# among pages already retrieved: second-order. Quotations come from the 2024
# lab GEO study and have not been shown on live engines.


def _recent_years(now: datetime | None = None) -> tuple[str, ...]:
    """This year and last: what "recent" means to an engine today."""
    year = (now or datetime.now(UTC)).year
    return (str(year - 1), str(year))


_YEAR_RE = re.compile(r"\b(20[0-9]{2})\b")
# An explicit price: currency symbol or code with an amount, optionally per period.
_PRICE_RE = re.compile(
    r"(?:[$€£¥]\s?\d[\d,]{0,15}(?:\.\d{1,2})?"
    r"|(?<![\d,.])\d[\d,]{0,15}(?:\.\d{1,2})?\s?(?:usd|eur|gbp)\b)",
    re.IGNORECASE,
)
# A visible or machine-readable "last updated" date.
# A visible "last updated" date, in the common formats: "Updated October 3,
# 2026", "Updated 3 October 2026", "Updated on Oct 3rd, 2026", "Last updated:
# 10/03/2026", "Reviewed 2026-10-03". The year must be 2010+ so "updated 2000
# records" doesn't count. Every repetition is bounded (third-party HTML).
_DATE = (
    r"(?:\d{1,2}(?:st|nd|rd|th)?\s{1,3})?(?:[a-z]{3,9}\.?\s{1,3})?"
    r"(?:\d{1,2}(?:st|nd|rd|th)?,?\s{1,3})?20[1-9]\d\b"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]20[1-9]\d\b|20[1-9]\d-\d{2}-\d{2}"
)
_UPDATED_RE = re.compile(
    r"\b(?:last\s{1,3})?(?:updated|reviewed|modified)\b\s{0,3}(?:on\b|:)?\s{0,3}(?:" + _DATE + ")",
    re.IGNORECASE,
)
# Machine-readable dates and ratings in the raw HTML (JSON-LD, <time>).
_UPDATED_MARKUP_RE = re.compile(r"\"datemodified\"|<time\b[^>]{0,200}?\bdatetime=", re.IGNORECASE)
_RATING_MARKUP = "aggregaterating"
_NON_VISIBLE = ("script", "style", "noscript", "template")


def _visible_html(html: str) -> str:
    """The HTML without <script>/<style>/<noscript>/<template> blocks, in one
    linear pass (a regex with a lazy body would go quadratic on unclosed
    tags). Feature checks for prices, ratings and dates read only what a
    visitor sees: "$1" in JavaScript or "aspect-ratio: 4/5" in CSS are not
    facts on the page."""
    lower = html.lower()
    out: list[str] = []
    i, n = 0, len(html)
    while i < n:
        start = lower.find("<", i)
        if start == -1:
            out.append(html[i:])
            break
        tag = next((t for t in _NON_VISIBLE if lower.startswith(t, start + 1)), None)
        if tag is None:
            out.append(html[i:start + 1])
            i = start + 1
            continue
        out.append(html[i:start])
        end = lower.find("</" + tag, start)
        if end == -1:
            break  # unclosed: drop the rest
        close = lower.find(">", end)
        i = n if close == -1 else close + 1
    return "".join(out)

# A rating: schema.org aggregateRating, or "4.6 out of 5" / "4.6 stars" / "4.6/5".
# A visible rating: "4.6 out of 5", "4.6/5", "4.6 stars", "5 stars". A bare
# "1/5" is too ambiguous (fractions, dates) to count without a decimal.
_RATING_RE = re.compile(
    r"\b[0-5]\.\d\s?(?:out of 5|/\s?5\b|stars?\b)|\b[0-5]\s?(?:out of 5\b|stars?\b)",
    re.IGNORECASE,
)

# Currency, percentages, scaled numbers, and any multi-digit figure — a proxy
# for "data-rich" (pages with 19+ data points earn 2-3x citations).
# Every quantifier below is bounded and digit runs can't start mid-run: these
# patterns run on third-party HTML, and unbounded `\d+`/`[\d,]*` go quadratic
# on a hostile page (a long digit run, "1,1,1,..." and so on).
_STAT_RE = re.compile(
    r"\$\s?\d[\d,]{0,15}(?:\.\d{1,4})?"
    r"|(?<![\d.])\d{1,9}(?:\.\d{1,4})?\s?%"
    r"|(?<![\d.])\d{1,9}(?:\.\d{1,4})?\s?(?:percent|million|billion|thousand|bps|x|×)\b"
    r"|\b\d{2,12}\b",
    re.IGNORECASE,
)
# Attributed quotations: a blockquote, or a quote-delimited span of real length.
_BLOCKQUOTE_RE = re.compile(r"<blockquote", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"“][^\"“”]{30,2000}[\"”]")
_HREF_RE = re.compile(r'href=["\'](https?://[^"\'#?\s]{1,2000})', re.IGNORECASE)
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


# Bounded so an unclosed tag can't make each match scan the rest of the page.
_HEADING_RE = re.compile(r"<h[1-4][^>]{0,300}>(.{0,600}?)</h[1-4]>", re.IGNORECASE | re.DOTALL)
_PARA_RE = re.compile(r"<p(?:\s[^>]{0,300})?>(.{0,4000}?)</p>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]{0,2000}>")
_MAX_HEADINGS = 300
_CAPSULE_WINDOW = 6000  # how far after a heading to look for its answer


def _has_answer_capsule(html: str) -> bool:
    """A ~40-60 word direct answer immediately under a question-format heading —
    72% of cited blog posts have one. Detected on HTML structure (robust to
    source line-wrapping): a question heading followed by a paragraph of
    answer-capsule length."""
    for i, m in enumerate(_HEADING_RE.finditer(html)):
        if i >= _MAX_HEADINGS:
            break
        heading = _TAG_RE.sub("", m.group(1)).strip()
        if heading.endswith("?") and len(heading.split()) <= 20:
            after = _PARA_RE.search(html, m.end(), m.end() + _CAPSULE_WINDOW)
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
    """Citability fingerprint in evidence order: explicit facts (price, update
    date, rating, latest year named) and evidence density first; then the
    second-order formatting signals (answer capsule, front-loading, quotations,
    cited sources, promotional tone); then machine-legibility hygiene (JSON-LD,
    FAQ schema, tables)."""
    lower = html.lower()
    visible = _visible_html(html)
    text, _ = extract_text_and_links(visible, ())
    word_count = len(text.split())

    statistic_count = sum(1 for _ in _STAT_RE.finditer(text))
    quotation_count = len(_BLOCKQUOTE_RE.findall(html)) + len(_QUOTE_RE.findall(text))
    citation_count = len({_host(u) for u in _HREF_RE.findall(html)})
    promo_hits = sum(lower.count(p) for p in _PROMO_PHRASES)
    promotional_tone_score = round(1000.0 * promo_hits / max(word_count, 1), 1)

    years = [int(y) for y in _YEAR_RE.findall(text) if int(y) <= datetime.now(UTC).year]
    return {
        # Explicit facts (controlled 2026 evidence: raise citation odds).
        "has_price": bool(_PRICE_RE.search(text)),
        "has_updated_date": bool(_UPDATED_MARKUP_RE.search(html) or _UPDATED_RE.search(text)),
        "has_rating": _RATING_MARKUP in lower or bool(_RATING_RE.search(text)),
        "latest_year": max(years) if years else 0,
        # Evidence density and second-order formatting.
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
        "recent_year_mentions": sum(len(re.findall(y, text)) for y in _recent_years()),
        "word_count": word_count,
    }


def crawl_page(client: httpx.Client, url: str) -> dict[str, Any]:
    """Fetch one page. Returns {html, http_status} or {error}."""
    try:
        # Stream and stop at the cap: a multi-GB response must not be pulled
        # into worker memory before truncation.
        with client.stream("GET", url, headers={"User-Agent": BROWSER_UA}) as resp:
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if len(buf) >= MAX_HTML_BYTES:
                    break
            encoding = resp.encoding or "utf-8"
            html = bytes(buf[:MAX_HTML_BYTES]).decode(encoding, errors="replace")
            return {"html": html, "http_status": resp.status_code}
    except httpx.HTTPError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "http_status": None}
