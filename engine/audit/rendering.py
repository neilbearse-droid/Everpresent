"""Client-side-rendering (CSR) dependency check (§AEO-plan M3).

The single most-repeated technical finding in the 2026 LLM-search research: **no
major AI crawler executes JavaScript.** GPTBot, ClaudeBot, and PerplexityBot
fetch raw HTML and never run it (Gemini via Googlebot and Applebot are the only
renderers). So a client-side-rendered SPA — an almost-empty HTML shell that
paints its content with JS in the browser — is a *blank page* to ChatGPT,
Claude, and Perplexity, no matter how good the content is.

This graders the page the way the engines see it: the raw document only, the
`view-source` view, never a headless render. Pure string/DOM inspection so it is
fully fixture-tested without a browser.
"""

import re
from typing import Any

from engine.retrievers.html_extract import extract_text_and_links

# Enough visible text in the raw HTML that the page is clearly server-rendered,
# whatever framework built it (an SSR'd Next.js page passes here).
_CONTENT_OK_WORDS = 250
# Below this, the raw document carries essentially no content of its own.
_CONTENT_MIN_WORDS = 60

# Empty SPA mount points: content is injected into these by JS after load.
_MOUNT_NODES = (
    'id="root"',
    "id='root'",
    'id="__next"',
    'id="app"',
    "id='app'",
    'data-reactroot',
    'ng-version',
    'id="__nuxt"',
)

# "Please enable JavaScript" interstitial copy — a direct tell that content is
# gated behind JS.
_NOSCRIPT_SIGNALS = (
    "enable javascript",
    "javascript is required",
    "please enable js",
    "you need to enable javascript to run this app",
)

_SCRIPT_TAG = re.compile(r"<script\b", re.IGNORECASE)


def render_verdict(html: str) -> dict[str, Any]:
    """Does the page's content live in the raw HTML, or only after JS runs?

    Returns {verdict: pass|warn|fail, word_count, reason, signals}. `pass` means
    AI crawlers can read the content; `fail` means they get a blank shell.
    """
    lower = html.lower()
    text, _ = extract_text_and_links(html, ())
    word_count = len(text.split())

    mount_node = any(node in lower for node in _MOUNT_NODES)
    noscript_warning = any(sig in lower for sig in _NOSCRIPT_SIGNALS)
    # Script-heavy = the document is mostly script markup, little prose.
    script_tags = len(_SCRIPT_TAG.findall(html))
    script_heavy = script_tags >= 3 and word_count < _CONTENT_MIN_WORDS

    signals = {
        "mount_node": mount_node,
        "noscript_warning": noscript_warning,
        "script_heavy": script_heavy,
    }

    # Content is present in the raw HTML — server-rendered, readable by every
    # crawler, regardless of the framework that produced it.
    if word_count >= _CONTENT_OK_WORDS:
        return {
            "verdict": "pass",
            "word_count": word_count,
            "reason": "Content is in the raw HTML — AI crawlers can read it.",
            "signals": signals,
        }

    # Almost-empty document with a JS app tell: a CSR shell, invisible to
    # non-rendering crawlers.
    if word_count < _CONTENT_MIN_WORDS and (mount_node or noscript_warning or script_heavy):
        return {
            "verdict": "fail",
            "word_count": word_count,
            "reason": (
                "The page ships a near-empty HTML shell and renders content with "
                "JavaScript. No major AI crawler runs JS, so ChatGPT, Claude, and "
                "Perplexity see a blank page. Server-side render or pre-render this "
                "template so revenue content (and schema/canonical/meta) lives in the "
                "raw HTML."
            ),
            "signals": signals,
        }

    # Some content, but thin or partly JS-dependent — worth a manual view-source.
    return {
        "verdict": "warn",
        "word_count": word_count,
        "reason": (
            "Thin raw HTML — some content may depend on JavaScript. Verify with "
            "view-source that revenue content is present without JS."
        ),
        "signals": signals,
    }
