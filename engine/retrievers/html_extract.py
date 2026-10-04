"""Shared HTML → (text, citations) extraction for Mode B adapters. Stdlib
only, so every adapter's parsing is unit-testable against recorded fixtures
without a browser."""

from html.parser import HTMLParser
from urllib.parse import urlparse

from engine.retrievers.openai_api import ParsedCitation

_BLOCK_TAGS = {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr", "pre"}


class _ExtractingParser(HTMLParser):
    def __init__(self, skip_host_fragments: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_host_fragments = skip_host_fragments
        self.parts: list[str] = []
        self.links: list[ParsedCitation] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        # Anchor nesting depth. Only the OUTERMOST <a> is captured, so an inner
        # nested anchor (invalid but occurs in scraped fragments) can't clobber
        # the outer link's href and drop it (§audit low).
        self._anchor_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self._anchor_depth += 1
            if self._anchor_depth == 1:
                href = dict(attrs).get("href") or ""
                host = (urlparse(href).hostname or "").lower() if href else ""
                # Match the link's HOST, not the whole URL: ChatGPT appends
                # ?utm_source=chatgpt.com to every outbound citation, and a
                # substring test on the full href dropped them all.
                if href.startswith("http") and not any(
                    host == f or host.endswith("." + f) for f in self.skip_host_fragments
                ):
                    self._href = href
                    self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_depth > 0:
            self._anchor_depth -= 1
            # Emit only when the outermost anchor closes.
            if self._anchor_depth == 0 and self._href:
                self.links.append(
                    ParsedCitation(url=self._href, title=" ".join(self._link_text).strip())
                )
                self._href = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data.strip())


def extract_text_and_links(
    html: str, skip_host_fragments: tuple[str, ...], *, split_ads: bool = True
) -> tuple[str, list[ParsedCitation]]:
    """Organic text and links. Sponsored blocks are cut out first, so a paid
    unit never counts as a mention or a citation (see engine/processing/ads)."""
    if split_ads:
        from engine.processing.ads import split_sponsored_html

        html, _ = split_sponsored_html(html)
    parser = _ExtractingParser(skip_host_fragments)
    parser.feed(html)
    lines = [line.strip() for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)
    seen: set[str] = set()
    citations = []
    for link in parser.links:
        if link.url not in seen:
            seen.add(link.url)
            citations.append(link)
    return text, citations
