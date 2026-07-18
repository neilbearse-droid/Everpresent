"""Mode B retriever: Microsoft Copilot's consumer web interface (§6.2).

Copilot has no API and is Bing-index-driven, so it behaves differently from the
four API surfaces and from the other two web surfaces — which is exactly why
the client wants it measured (large hosting-category swings show up here first).
Same fresh-session pattern as chatgpt_web/perplexity_web: a clean context per
query, the persona preamble + query as the opening message, the rendered answer
and its source links captured, the context destroyed.

Copilot redesigns its DOM often, so every selector is a candidate LIST resolved
at runtime (copilot_web_selectors.py) and the adapter degrades gracefully:
missing submit button → press Enter; missing stop button → rely on DOM
stability. Parsing is the shared stdlib extractor."""

import asyncio
import time

from engine.retrievers import copilot_web_selectors as sel
from engine.retrievers.blocking import assert_not_blocked
from engine.retrievers.chatgpt_web import WebRetrievalOutcome, build_opening_message
from engine.retrievers.html_extract import extract_text_and_links
from engine.retrievers.stealth import ScrapeEnv, browser_page

ADAPTER_VERSION = "v3.1.0"

# Copilot cites external sources but its own chrome links back to Microsoft
# properties; drop those so only real answer citations survive.
_SKIP_HOST_FRAGMENTS = (
    "copilot.microsoft.com",
    "microsoft.com",
    "bing.com",
    "go.microsoft.com",
    "microsoftapp.net",
)


def parse_answer_html(html: str) -> tuple[str, list]:
    return extract_text_and_links(html, _SKIP_HOST_FRAGMENTS)


async def _first_matching(page, candidates: list[str]):
    """The first locator in `candidates` that matches at least one node, or
    None. Keeps the adapter resilient to Copilot's frequent composer rewrites."""
    for selector in candidates:
        locator = page.locator(selector)
        try:
            if await locator.count() > 0:
                return locator
        except Exception:  # noqa: BLE001 — a bad selector shouldn't abort the scan
            continue
    return None


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
        # Layer 0: bail early with a clear reason if we hit an anti-bot wall.
        await assert_not_blocked(page)

        for dismiss in sel.DISMISS_CANDIDATES:
            try:
                await page.locator(dismiss).first.click(timeout=2_000)
            except Exception:  # noqa: BLE001 — interstitials are optional
                pass

        prompt = await _first_matching(page, sel.PROMPT_INPUT_CANDIDATES)
        if prompt is None:
            raise RuntimeError("copilot composer not found (selectors need updating)")
        prompt = prompt.first
        await prompt.wait_for(state="visible", timeout=30_000)
        await prompt.fill(build_opening_message(persona_prompt, query_text))

        submit = await _first_matching(page, sel.SUBMIT_BUTTON_CANDIDATES)
        if submit is not None:
            await submit.first.click(timeout=10_000)
        else:
            # No submit button matched — the composer submits on Enter.
            await prompt.press("Enter")

        answer = await _first_matching(page, sel.ANSWER_CONTAINER_CANDIDATES)
        if answer is None:
            # The answer node may not exist until the model starts responding;
            # give it a beat, then re-resolve once.
            await asyncio.sleep(3.0)
            answer = await _first_matching(page, sel.ANSWER_CONTAINER_CANDIDATES)
        if answer is None:
            raise RuntimeError("copilot answer container not found (selectors need updating)")
        answer = answer.last
        await answer.wait_for(state="attached", timeout=60_000)

        # Completion = streaming indicator gone (best-effort — Copilot doesn't
        # always render one) and the DOM stable twice in a row.
        previous_html = ""
        stable = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            current_html = await answer.inner_html()
            stop = await _first_matching(page, sel.STOP_BUTTON_CANDIDATES)
            streaming = stop is not None and await stop.count() > 0
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
