#!/usr/bin/env python
"""Live smoke test for the Microsoft Copilot Mode B adapter (§step 2).

Drives the REAL selectors (copilot_web_selectors.py) and the REAL parser
(copilot_web.parse_answer_html) against live Copilot, stage by stage, so a
failure tells you exactly which step broke — and saves a screenshot at each
stage plus on error. Also reports whether Reddit / YouTube show up in the
citations (the Airo-segment question).

This is a diagnostic tool, not part of the app. Run it where Playwright and a
real (ideally residential) IP exist — the scrape worker container, or locally:

    pip install playwright && playwright install chromium
    python scripts/smoke_copilot.py --query "What's the best AI website builder?"

Options:
    --query TEXT         the question to ask (default: an Airo/Reddit-heavy one)
    --persona TEXT       first-person preamble prepended to the query
    --headful            show the browser (default: headless)
    --timeout SECONDS    answer-settle timeout (default: 90)
    --executable-path P  Chromium binary (default: $CHROMIUM_PATH or Playwright's)
    --proxy URL          http://user:pass@host:port (residential recommended)
    --out DIR            where to write screenshots (default: ./copilot-smoke)

Exit code 0 = a parsed answer came back; non-zero = blocked / selectors / timeout.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Reuse the ACTUAL adapter pieces so this validates the shipped code, not a copy.
from engine.retrievers import copilot_web_selectors as sel
from engine.retrievers.blocking import BlockedError, assert_not_blocked
from engine.retrievers.chatgpt_web import build_opening_message
from engine.retrievers.copilot_web import (
    _SKIP_HOST_FRAGMENTS,
    _first_matching,
    parse_answer_html,
)

DEFAULT_QUERY = "What's the best AI website builder?"
DEFAULT_PERSONA = (
    "I'm setting up my new business right now. I haven't launched yet, and I'm "
    "building the website and need to sell online and manage customers."
)


def log(stage: str, msg: str) -> None:
    print(f"[{stage:<9}] {msg}", flush=True)


async def run(args: argparse.Namespace) -> int:
    from playwright.async_api import async_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []

    async def shot(name: str, page) -> None:
        p = out / f"{name}.png"
        try:
            await page.screenshot(path=str(p), full_page=False)
            shots.append(p)
            log("shot", str(p))
        except Exception as exc:  # noqa: BLE001
            log("shot", f"could not capture {name}: {exc}")

    launch: dict = {"headless": not args.headful}
    if args.executable_path:
        launch["executable_path"] = args.executable_path
    if args.proxy:
        launch["proxy"] = {"server": args.proxy}

    started = time.monotonic()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch)
        context = await browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        try:
            log("goto", sel.URL)
            await page.goto(sel.URL, wait_until="domcontentloaded", timeout=60_000)

            try:
                await assert_not_blocked(page)
                log("block", "no anti-bot wall detected")
            except BlockedError as exc:
                await shot("99-blocked", page)
                log("BLOCKED", f"{exc.reason} — needs a residential proxy from this IP")
                return 3

            for dismiss in sel.DISMISS_CANDIDATES:
                try:
                    await page.locator(dismiss).first.click(timeout=1_500)
                    log("dismiss", f"clicked {dismiss}")
                except Exception:  # noqa: BLE001
                    pass
            await shot("01-loaded", page)

            prompt = await _first_matching(page, sel.PROMPT_INPUT_CANDIDATES)
            if prompt is None:
                await shot("99-no-composer", page)
                log("FAIL", "composer not found — update PROMPT_INPUT_CANDIDATES")
                return 4
            matched = next(
                (s for s in sel.PROMPT_INPUT_CANDIDATES
                 if await page.locator(s).count() > 0), "?")
            log("composer", f"matched: {matched}")
            prompt = prompt.first
            await prompt.wait_for(state="visible", timeout=30_000)
            await prompt.fill(build_opening_message(args.persona, args.query))

            submit = await _first_matching(page, sel.SUBMIT_BUTTON_CANDIDATES)
            if submit is not None:
                await submit.first.click(timeout=10_000)
                log("submit", "clicked submit button")
            else:
                await prompt.press("Enter")
                log("submit", "no submit button matched — pressed Enter (adapter fallback)")
            await shot("02-submitted", page)

            answer = await _first_matching(page, sel.ANSWER_CONTAINER_CANDIDATES)
            if answer is None:
                await asyncio.sleep(3.0)
                answer = await _first_matching(page, sel.ANSWER_CONTAINER_CANDIDATES)
            if answer is None:
                await shot("99-no-answer", page)
                log("FAIL", "answer container not found — update ANSWER_CONTAINER_CANDIDATES")
                return 5
            answer = answer.last
            await answer.wait_for(state="attached", timeout=60_000)

            deadline = started + args.timeout
            previous_html, stable = "", 0
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
                await shot("99-timeout", page)
                log("FAIL", f"answer did not settle within {args.timeout}s")
                return 6

            fragment = await answer.inner_html()
            await shot("03-answer", page)
            text, citations = parse_answer_html(fragment)

            domains = [c.domain for c in citations]
            reddit = [d for d in domains if "reddit" in d]
            youtube = [d for d in domains if "youtube" in d or "youtu.be" in d]

            print("\n" + "=" * 64)
            log("OK", f"answer settled in {int(time.monotonic() - started)}s, "
                      f"{len(text)} chars, {len(citations)} citations")
            print("-" * 64)
            print("ANSWER (first 600 chars):\n" + text[:600])
            print("-" * 64)
            print(f"CITATION DOMAINS ({len(domains)}): "
                  + (", ".join(sorted(set(domains))) or "(none captured)"))
            print(f"  reddit:  {'YES — ' + ', '.join(reddit) if reddit else 'no'}")
            print(f"  youtube: {'YES — ' + ', '.join(youtube) if youtube else 'no'}")
            skip = ", ".join(_SKIP_HOST_FRAGMENTS)
            print(f"  (chrome hosts stripped: {skip})")
            print("=" * 64)
            if not domains:
                log("WARN", "answer parsed but NO citations captured — Copilot may render "
                            "sources in a node outside the answer container; widen "
                            "ANSWER_CONTAINER_CANDIDATES or add a citations selector")
            return 0
        except Exception as exc:  # noqa: BLE001
            await shot("99-error", page)
            log("ERROR", f"{type(exc).__name__}: {exc}")
            return 2
        finally:
            await context.close()
            await browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Live smoke test for the Copilot adapter")
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--persona", default=DEFAULT_PERSONA)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--executable-path", default=os.environ.get("CHROMIUM_PATH", ""))
    ap.add_argument("--proxy", default="")
    ap.add_argument("--out", default="./copilot-smoke")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args))
    except ModuleNotFoundError as exc:
        print(f"Playwright not installed: {exc}\n"
              "Run: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
