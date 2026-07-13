"""Shared HTML → (text, citations) extraction for Mode B adapters. Stdlib
only, so every adapter's parsing is unit-testable against recorded fixtures
without a browser."""

from html.parser import HTMLParser

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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http") and not any(
                fragment in href for fragment in self.skip_host_fragments
            ):
                self._href = href
                self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append(
                ParsedCitation(url=self._href, title=" ".join(self._link_text).strip())
            )
            self._href = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data.strip())


def extract_text_and_links(
    html: str, skip_host_fragments: tuple[str, ...]
) -> tuple[str, list[ParsedCitation]]:
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
