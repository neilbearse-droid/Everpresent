"""Is a page in Brave Search's index?

Claude's web search runs on Brave (Anthropic's subprocessor list, March
2025), and Brave's crawler follows Googlebot's robots rules rather than
advertising its own user agent. So a page Brave hasn't indexed can't reach
a Claude answer, and a page Googlebot can't crawl won't reach Brave. One
query per page against Brave's Search API: the page's own URL, matched
against the result URLs with scheme, www and trailing slash ignored."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

API_URL = "https://api.search.brave.com/res/v1/web/search"
TIMEOUT_S = 10.0


def normalize_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = (parts.path or "/").rstrip("/") or "/"
    return f"{host}{path}".lower()


def brave_indexed(api_key: str, url: str, client: httpx.Client | None = None) -> bool | None:
    """True if Brave returns the page for a query of its own URL, False if the
    query succeeds without it, None when the check couldn't run (no key, an
    API error, a rate limit)."""
    if not api_key or not url:
        return None
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        resp = c.get(
            API_URL,
            params={"q": url, "count": 10},
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        )
        if resp.status_code != 200:
            return None
        results = ((resp.json() or {}).get("web") or {}).get("results") or []
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            c.close()
    want = normalize_url(url)
    return any(normalize_url(str(r.get("url") or "")) == want for r in results)
