"""Shared Playwright launch + context construction for the Mode B surfaces
(§SCRAPING_V3 Layers 1–3). Every scraping adapter builds its browser the same
way so anti-detection, proxy routing, and geo/locale are consistent and live in
one place.

Nothing here is vendor-specific: a proxy is a URL, a managed browser is a CDP
endpoint. All of it is off by default and activates only when configured, so
CI and unconfigured deployments launch a plain local Chromium exactly as
before.

Playwright is imported lazily (scrape worker only), so this module stays
importable in browser-free test/CI environments."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# A current, common desktop Chrome UA. Kept realistic (not a headless string)
# so naive UA sniffing doesn't flag us. Bump alongside the bundled Chromium.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Country code -> a plausible IANA timezone, so a geo-targeted request doesn't
# present a UTC clock from an Ashburn datacenter. Coarse but enough to be
# consistent with the exit IP's country.
_TZ_BY_COUNTRY = {
    "us": "America/New_York",
    "ca": "America/Toronto",
    "gb": "Europe/London",
    "uk": "Europe/London",
    "au": "Australia/Sydney",
    "de": "Europe/Berlin",
    "fr": "Europe/Paris",
    "in": "Asia/Kolkata",
    "sg": "Asia/Singapore",
    "ae": "Asia/Dubai",
    "jp": "Asia/Tokyo",
}

# Launch flags that remove the most common automation tells.
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# Injected before any page script runs: erase navigator.webdriver and give
# headless Chrome the plugin/language shape a real browser has.
_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = window.chrome || {runtime: {}};
"""


@dataclass
class ScrapeEnv:
    """Everything the launch layer needs, resolved from Settings + the request's
    geo. Adapters build one of these and hand it to `browser_page`."""

    headless: bool = True
    executable_path: str | None = None
    # Proxy selection: an explicit URL wins; otherwise `proxy_map[country]`;
    # otherwise `proxy_url`; otherwise no proxy.
    proxy_url: str = ""
    proxy_map: dict[str, str] = field(default_factory=dict)
    # A managed scraping browser (Layer 3). When set, we connect over CDP
    # instead of launching local Chromium — the provider handles proxy+captcha.
    cdp_endpoint: str = ""
    stealth: bool = True
    # Request geo (from a Location or the tenant default).
    country: str = "ca"
    language: str = "en"
    latitude: float | None = None
    longitude: float | None = None
    user_agent: str = DEFAULT_USER_AGENT
    # Abort image/media/font requests (§SCRAPING_V3 cost). We parse only text
    # and links, so these bytes are pure proxy cost — dropping them roughly
    # halves GB/scrape with no loss of measurement fidelity. Stylesheets and
    # scripts are kept so layout-dependent capture (AIO block vs organic
    # position) stays accurate.
    block_assets: bool = True


# Resource types safe to abort: never parsed, and don't affect the DOM layout
# the capture relies on.
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


def resolve_proxy(env: ScrapeEnv) -> str:
    """Country-specific proxy → default proxy → none. Public for testing."""
    country = (env.country or "").lower()
    if country and env.proxy_map.get(country):
        return env.proxy_map[country]
    return env.proxy_url or ""


def _proxy_setting(proxy_url: str) -> dict[str, Any] | None:
    """Split a proxy URL into Playwright's {server, username, password}."""
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    setting: dict[str, Any] = {"server": server}
    if parsed.username:
        setting["username"] = parsed.username
    if parsed.password:
        setting["password"] = parsed.password
    return setting


def timezone_for(country: str) -> str:
    return _TZ_BY_COUNTRY.get((country or "").lower(), "UTC")


def context_options(env: ScrapeEnv) -> dict[str, Any]:
    """The new_context kwargs for this request — locale, timezone, UA, geo, and
    proxy. Broken out so tests can assert the shape without a browser."""
    opts: dict[str, Any] = {
        "locale": f"{env.language}-{env.country.upper()}" if env.country else env.language,
        "timezone_id": timezone_for(env.country),
        "user_agent": env.user_agent,
        "extra_http_headers": {
            "Accept-Language": f"{env.language}-{env.country.upper()},{env.language};q=0.9"
        },
    }
    if env.latitude is not None and env.longitude is not None:
        opts["geolocation"] = {"latitude": env.latitude, "longitude": env.longitude}
        opts["permissions"] = ["geolocation"]
    proxy = resolve_proxy(env)
    if proxy:
        setting = _proxy_setting(proxy)
        if setting:
            opts["proxy"] = setting
    return opts


async def _route_blocker(route) -> None:
    """Abort never-parsed heavy resources to cut proxy bytes; let everything
    else through."""
    if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


@asynccontextmanager
async def browser_page(env: ScrapeEnv):
    """Yield a fresh (browser, context, page) for one scrape and tear it all
    down afterwards. Local Chromium by default; a managed browser over CDP when
    `cdp_endpoint` is set. The fresh-context-per-query guarantee is preserved."""
    from playwright.async_api import async_playwright  # lazy: scrape worker only

    async with async_playwright() as pw:
        if env.cdp_endpoint:
            browser = await pw.chromium.connect_over_cdp(env.cdp_endpoint)
        else:
            browser = await pw.chromium.launch(
                headless=env.headless,
                executable_path=env.executable_path or None,
                args=_STEALTH_ARGS if env.stealth else [],
            )
        try:
            context = await browser.new_context(**context_options(env))
            if env.stealth:
                await context.add_init_script(_INIT_SCRIPT)
            if env.block_assets:
                await context.route("**/*", _route_blocker)
            page = await context.new_page()
            try:
                yield browser, context, page
            finally:
                await context.close()  # destroy the session, no memory carryover
        finally:
            await browser.close()
