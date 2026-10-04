"""Sponsored units in AI answers, kept apart from the organic answer.

Answer engines now sell placements inside or under answers (ChatGPT
"Sponsored" units, ads in Google AI Overviews and AI Mode). A paid unit that
names a brand is not organic visibility, so:

  - `split_sponsored_html` cuts sponsored blocks out of a captured answer's
    HTML before text and citations are extracted, and returns them as units;
  - `sponsored_from_serp` reads the ad blocks a SerpApi payload carries.

Detection is deliberately conservative: an element counts as sponsored when
its attributes say so (data-testid / aria-label / class / data-ad*), or when
it is the smallest block, at most a few levels above a standalone
"Sponsored" / "Ad" label, that also contains a link. Prose that merely uses
the word "sponsored" is never cut. Stdlib only.
"""

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

LABELS = {"sponsored", "ad", "ads", "sponsored result", "sponsored results", "advertisement",
          "promoted"}
_ATTR_MARKERS = ("sponsor", "advertis", "ad-unit", "ad_unit", "adunit", "promoted")
_LABEL_REACH = 4  # levels above the label we look for the ad card
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "source", "track", "wbr"}


@dataclass
class SponsoredUnit:
    title: str
    url: str
    text: str
    placement: str  # in_answer | serp

    @property
    def domain(self) -> str:
        return (urlparse(self.url).hostname or "").lower().removeprefix("www.")

    def as_dict(self) -> dict[str, str]:
        return {**asdict(self), "domain": self.domain}


def _attr_says_ad(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if name.startswith("data-ad"):
            return True
        if name in ("data-testid", "aria-label", "class", "id", "data-type", "role") and value:
            v = value.lower()
            if any(m in v for m in _ATTR_MARKERS):
                return True
            if name == "aria-label" and v.strip() in LABELS:
                return True
    return False


class _Frame:
    __slots__ = ("tag", "start", "attr_ad", "label_at", "link")

    def __init__(self, tag: str, start: int, attr_ad: bool) -> None:
        self.tag, self.start, self.attr_ad = tag, start, attr_ad
        self.label_at: int | None = None  # levels below this frame where a label sits
        self.link = False


class _SpanFinder(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.html = html
        self._line_offsets = [0]
        # getpos() counts "\n" only, so offsets must too (not splitlines()).
        for line in html.split("\n"):
            self._line_offsets.append(self._line_offsets[-1] + len(line) + 1)
        self.stack: list[_Frame] = []
        self.spans: list[tuple[int, int]] = []

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        start = self._offset()
        if tag in _VOID:
            return
        frame = _Frame(tag, start, _attr_says_ad(attrs))
        if tag == "a" and (dict(attrs).get("href") or "").startswith("http"):
            frame.link = True
        self.stack.append(frame)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass

    def handle_data(self, data: str) -> None:
        if data.strip().lower().rstrip(":·•").strip() in LABELS and self.stack:
            self.stack[-1].label_at = 0

    def handle_endtag(self, tag: str) -> None:
        # Close back to the matching open tag (tolerates unclosed children).
        idx = next((i for i in range(len(self.stack) - 1, -1, -1)
                    if self.stack[i].tag == tag), None)
        if idx is None:
            return
        end = self._offset()
        rest = self.html[end:]
        close = rest.find(">")
        end = end + close + 1 if close >= 0 else len(self.html)
        while len(self.stack) > idx:
            frame = self.stack.pop()
            parent = self.stack[-1] if self.stack else None
            is_ad = frame.attr_ad or (frame.label_at is not None and frame.link)
            if is_ad:
                self.spans.append((frame.start, end))
                continue  # consumed: nothing propagates to the parent
            if parent is not None:
                parent.link = parent.link or frame.link
                if frame.label_at is not None and frame.label_at < _LABEL_REACH:
                    lvl = frame.label_at + 1
                    parent.label_at = lvl if parent.label_at is None else min(parent.label_at, lvl)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def split_sponsored_html(html: str) -> tuple[str, list[SponsoredUnit]]:
    """(organic_html, sponsored units). Returns the input untouched when no
    sponsored block is found."""
    if not html or ("ponsor" not in html and "dvert" not in html and ">Ad" not in html
                    and "data-ad" not in html and "romoted" not in html):
        return html, []
    finder = _SpanFinder(html)
    try:
        finder.feed(html)
        finder.close()
    except Exception:  # noqa: BLE001 — malformed capture: keep it whole
        return html, []
    spans = _merge(finder.spans)
    if not spans:
        return html, []
    from engine.retrievers.html_extract import extract_text_and_links

    units: list[SponsoredUnit] = []
    organic, cursor = [], 0
    for s, e in spans:
        organic.append(html[cursor:s])
        cursor = e
        text, links = extract_text_and_links(html[s:e], (), split_ads=False)
        lines = [ln for ln in text.splitlines() if ln.strip().lower() not in LABELS]
        title = (links[0].title if links and links[0].title else (lines[0] if lines else ""))
        units.append(SponsoredUnit(title=title[:200], url=links[0].url if links else "",
                                   text=" ".join(lines)[:500], placement="in_answer"))
    organic.append(html[cursor:])
    return "".join(organic), units


_SERP_AD_KEYS = ("ads", "top_ads", "bottom_ads", "sponsored_results", "shopping_ads",
                 "inline_ads")


def sponsored_from_serp(payload: dict[str, Any]) -> list[SponsoredUnit]:
    """Ad blocks from a SerpApi response (AI Mode / Google)."""
    units: list[SponsoredUnit] = []
    for key in _SERP_AD_KEYS:
        for ad in payload.get(key) or []:
            if not isinstance(ad, dict):
                continue
            url = str(ad.get("link") or ad.get("tracking_link") or ad.get("displayed_link") or "")
            if url and "://" not in url:
                url = "https://" + url
            units.append(SponsoredUnit(
                title=str(ad.get("title") or ad.get("source") or "")[:200],
                url=url,
                text=str(ad.get("description") or ad.get("snippet") or "")[:500],
                placement="serp",
            ))
    return units
