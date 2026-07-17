"""Block/challenge detection for the Mode B surfaces (§SCRAPING_V3 Layer 0).

The point is signal integrity: a Cloudflare interstitial, a Google "unusual
traffic" wall, or a login gate must NOT be recorded as "the brand is absent from
the answer". We fingerprint the rendered page and, on a match, raise
`BlockedError` — which the job records as `ResultStatus.blocked`, kept out of
the absent/negative scoring entirely.

Detection is pure string inspection over the page's URL, title, and text, so it
is fully unit-testable without a browser."""

from dataclasses import dataclass

# Lower-cased substrings that only appear on a challenge/consent/login wall,
# never in a genuine answer. Kept conservative to avoid false positives — a
# real answer discussing "captcha" as a topic won't contain these exact frames.
_BLOCK_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("just a moment...", "cloudflare"),
    ("checking your browser before accessing", "cloudflare"),
    ("cf-browser-verification", "cloudflare"),
    ("cf-challenge", "cloudflare"),
    ("attention required! | cloudflare", "cloudflare"),
    ("unusual traffic from your computer network", "google_sorry"),
    ("our systems have detected unusual traffic", "google_sorry"),
    ("/sorry/index", "google_sorry"),
    ("to continue, please type the characters", "captcha"),
    ("recaptcha/api2", "captcha"),
    ("hcaptcha.com/captcha", "captcha"),
    ("g-recaptcha", "captcha"),
    ("enable javascript and cookies to continue", "js_wall"),
)

# Ambiguous phrases that occur in genuine answers (e.g. an answer explaining
# HTTP 429). These signal a block ONLY when they are the page TITLE — a wall
# puts them front-and-center; a real answer buries them mid-body. Matched
# against the title only to avoid dropping real answers as "blocked".
_BLOCK_TITLE_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("verify you are a human", "captcha"),
    ("access denied", "access_denied"),
    ("you have been blocked", "access_denied"),
    ("rate limit exceeded", "rate_limited"),
    ("too many requests", "rate_limited"),
)

# URL fragments that mean we were bounced to a challenge endpoint.
_BLOCK_URL_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("/sorry/", "google_sorry"),
    ("/challenge", "cloudflare"),
    ("captcha", "captcha"),
)


class BlockedError(Exception):
    """Raised when a scrape hit an anti-bot wall rather than a real answer. The
    `.reason` is the fingerprint family (cloudflare, captcha, …) for reporting."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(f"blocked: {reason}" + (f" ({detail})" if detail else ""))


@dataclass
class BlockCheck:
    blocked: bool
    reason: str = ""


def detect_block(*, url: str = "", title: str = "", body_text: str = "") -> BlockCheck:
    """Inspect a page for challenge fingerprints. Any field may be empty."""
    haystack = f"{title}\n{body_text}".lower()
    for needle, reason in _BLOCK_SIGNATURES:
        if needle in haystack:
            return BlockCheck(True, reason)
    low_title = (title or "").lower()
    for needle, reason in _BLOCK_TITLE_SIGNATURES:
        if needle in low_title:
            return BlockCheck(True, reason)
    low_url = (url or "").lower()
    for fragment, reason in _BLOCK_URL_FRAGMENTS:
        if fragment in low_url:
            return BlockCheck(True, reason)
    return BlockCheck(False)


async def assert_not_blocked(page) -> None:
    """Read the live page and raise BlockedError on a challenge. Called by the
    adapters right after navigation, before they wait for answer content —
    catching the block early avoids a misleading content-timeout."""
    try:
        url = page.url
        title = await page.title()
        # Body text only; full HTML would inflate false positives on scripts.
        body_text = await page.inner_text("body")
    except Exception:  # noqa: BLE001 — if we can't read the page, let the caller time out
        return
    check = detect_block(url=url, title=title, body_text=body_text)
    if check.blocked:
        raise BlockedError(check.reason, url[:120])
