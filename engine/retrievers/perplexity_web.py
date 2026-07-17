"""Mode B retriever: Perplexity's consumer web interface (§6.2, second
adapter). Same fresh-session pattern as chatgpt_web: clean context per
query, persona framing + query as the opening message, rendered answer and
source links captured, context destroyed. Selectors live in
perplexity_web_selectors.py; parsing is shared stdlib extraction."""

import asyncio
import time

from engine.retrievers import perplexity_web_selectors as sel
from engine.retrievers.blocking import assert_not_blocked
from engine.retrievers.chatgpt_web import WebRetrievalOutcome, build_opening_message
from engine.retrievers.html_extract import extract_text_and_links
from engine.retrievers.stealth import ScrapeEnv, browser_page

ADAPTER_VERSION = "v3.1.0"

_SKIP_HOST_FRAGMENTS = ("perplexity.ai", "pplx.ai")


def parse_answer_html(html: str) -> tuple[str, list]:
    return extract_text_and_links(html, _SKIP_HOST_FRAGMENTS)


async def retrieve(
    persona_prompt: str,
    query_text: str,
    *,
    headless: bool = True,
    timeout_s: float = 240.0,
    executable_path: str | None = None,
    env: ScrapeEnv | None = None,
) -> WebRetrievalOutcome:
    env = env or ScrapeEnv(headless=headless, executable_path=executable_path)

    started = time.monotonic()
    deadline = started + timeout_s
    async with browser_page(env) as (_browser, _context, page):
        await page.goto(sel.URL, wait_until="domcontentloaded", timeout=60_000)
        await assert_not_blocked(page)

        for dismiss in sel.DISMISS_CANDIDATES:
            try:
                await page.locator(dismiss).first.click(timeout=2_000)
            except Exception:  # noqa: BLE001 — interstitials are optional
                pass

        prompt = page.locator(sel.PROMPT_INPUT).first
        await prompt.wait_for(state="visible", timeout=30_000)
        await prompt.fill(build_opening_message(persona_prompt, query_text))
        await page.locator(sel.SUBMIT_BUTTON).first.click(timeout=10_000)

        answer = page.locator(sel.ANSWER_CONTAINER).last
        await answer.wait_for(state="attached", timeout=60_000)

        previous_html = ""
        stable = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            current_html = await answer.inner_html()
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

        fragment = await answer.inner_html()
        text, citations = parse_answer_html(fragment)
        return WebRetrievalOutcome(
            text=text,
            citations=citations,
            html_fragment=fragment,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
