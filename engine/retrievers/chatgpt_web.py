"""Mode B retriever: the ChatGPT consumer web interface via Playwright
(§6.2). The v1 fresh-session pattern: a clean browser context per query, the
persona framing and query submitted as the opening message, the rendered
answer captured, the context destroyed. No account memory ever contaminates a
result.

Playwright is imported lazily so this module stays importable (and CI stays
browser-free) outside the scraping worker; live scraping happens only in the
dedicated container. DOM selectors live in chatgpt_web_selectors.py, nothing
else knows them."""

import asyncio
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser

from engine.retrievers import chatgpt_web_selectors as sel
from engine.retrievers.openai_api import ParsedCitation

ADAPTER_VERSION = "v3.0.0"

_BLOCK_TAGS = {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr", "pre"}
_SKIP_HOST_FRAGMENTS = ("chatgpt.com", "openai.com", "oaiusercontent.com")


@dataclass
class WebRetrievalOutcome:
    text: str
    citations: list[ParsedCitation] = field(default_factory=list)
    html_fragment: str = ""  # the assistant message's rendered HTML
    latency_ms: int = 0


class _AssistantHTMLParser(HTMLParser):
    """Extracts readable text and outbound source links from an assistant
    message's rendered HTML. Stdlib-only so it is unit-testable against
    recorded fixtures without a browser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[ParsedCitation] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http") and not any(f in href for f in _SKIP_HOST_FRAGMENTS):
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


def parse_assistant_html(html: str) -> tuple[str, list[ParsedCitation]]:
    parser = _AssistantHTMLParser()
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


def build_opening_message(persona_prompt: str, query_text: str) -> str:
    """Persona framing + query as one opening message (DECISIONS.md M4)."""
    return f"{persona_prompt.strip()}\n\n{query_text.strip()}"


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    headless: bool = True,
    timeout_s: float = 240.0,
    executable_path: str | None = None,
) -> WebRetrievalOutcome:
    from playwright.async_api import async_playwright  # lazy: scrape worker only

    started = time.monotonic()
    deadline = started + timeout_s
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            executable_path=executable_path or None,
        )
        try:
            # Fresh context per query — the whole point of the pattern.
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(sel.URL, wait_until="domcontentloaded", timeout=60_000)

            for dismiss in sel.DISMISS_CANDIDATES:
                try:
                    await page.locator(dismiss).first.click(timeout=2_000)
                except Exception:  # noqa: BLE001 — interstitials are optional
                    pass

            prompt = page.locator(sel.PROMPT_INPUT)
            await prompt.wait_for(state="visible", timeout=30_000)
            await prompt.fill(build_opening_message(persona_prompt, query_text))
            await page.locator(sel.SEND_BUTTON).click(timeout=10_000)

            message = page.locator(sel.ASSISTANT_MESSAGE).last
            await message.wait_for(state="attached", timeout=60_000)

            # Completion = streaming indicator gone and DOM stable twice over.
            previous_html = ""
            stable = 0
            while time.monotonic() < deadline:
                await asyncio.sleep(1.5)
                current_html = await message.inner_html()
                streaming = await page.locator(sel.STOP_BUTTON).count() > 0
                if current_html == previous_html and not streaming and current_html:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                previous_html = current_html
            else:
                raise TimeoutError(f"answer did not settle within {timeout_s}s")

            fragment = await message.inner_html()
            text, citations = parse_assistant_html(fragment)
            await context.close()  # destroy the session, no memory carryover
            return WebRetrievalOutcome(
                text=text,
                citations=citations,
                html_fragment=fragment,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            await browser.close()
