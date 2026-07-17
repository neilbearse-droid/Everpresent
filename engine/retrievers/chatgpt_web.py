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

from engine.retrievers import chatgpt_web_selectors as sel
from engine.retrievers.blocking import assert_not_blocked
from engine.retrievers.html_extract import extract_text_and_links
from engine.retrievers.openai_api import ParsedCitation
from engine.retrievers.stealth import ScrapeEnv, browser_page

ADAPTER_VERSION = "v3.1.0"

_SKIP_HOST_FRAGMENTS = ("chatgpt.com", "openai.com", "oaiusercontent.com")


@dataclass
class WebRetrievalOutcome:
    text: str
    citations: list[ParsedCitation] = field(default_factory=list)
    html_fragment: str = ""  # the assistant message's rendered HTML
    latency_ms: int = 0


def parse_assistant_html(html: str) -> tuple[str, list[ParsedCitation]]:
    return extract_text_and_links(html, _SKIP_HOST_FRAGMENTS)


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
    env: ScrapeEnv | None = None,
) -> WebRetrievalOutcome:
    """Scrape one answer. `env` (stealth/proxy/geo) is used when provided;
    otherwise a plain local-Chromium env is built from headless/executable_path
    for backward compatibility."""
    env = env or ScrapeEnv(headless=headless, executable_path=executable_path)

    started = time.monotonic()
    deadline = started + timeout_s
    async with browser_page(env) as (_browser, _context, page):
        await page.goto(sel.URL, wait_until="domcontentloaded", timeout=60_000)
        # Layer 0: bail early with a clear reason if we hit an anti-bot wall.
        await assert_not_blocked(page)

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
        return WebRetrievalOutcome(
            text=text,
            citations=citations,
            html_fragment=fragment,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
