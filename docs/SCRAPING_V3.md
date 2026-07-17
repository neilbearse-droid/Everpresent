# Mode B Scraping v3 — Anti-Blocking & Location-Based Queries

This spec covers the two capabilities the enterprise engagement requires of the
web-scraping surfaces (ChatGPT web, Perplexity web, Google AIO):

1. **Survive bot-blocking** from datacenter IPs, consent walls, and captchas —
   and, just as important, *know when we were blocked* instead of silently
   recording a false "not mentioned".
2. **Location-based queries** — measure the same corpus as it appears to users
   in specific cities/countries, and slice visibility by location.

The design's organizing insight: **these are one problem, not two.** A
residential proxy that exits in the target city (a) is not a datacenter IP, so
it dodges the blocking that killed direct capture, and (b) makes the AI answer
and SERP genuinely localized. One mechanism, both outcomes.

---

## Part 1 — Anti-blocking: defense in depth, cheapest-first

We add capability in four layers. Each is independently valuable and activates
only when configured, so we spend money only where a cheaper layer wasn't
enough.

### Layer 0 — Block detection (free; ship first)

Before anything else, we must distinguish *blocked* from *absent*. Today a
Cloudflare interstitial, a Google "unusual traffic" wall, or a login gate all
land as an empty or errored scrape — which downstream reads as "the brand isn't
in the answer". For a client paying for visibility measurement, a false
negative is worse than a gap in coverage.

`engine/retrievers/blocking.py` scans the rendered page (URL, title, body text,
and known selectors) for challenge fingerprints:

- Cloudflare / "Just a moment…" / "Checking your browser"
- Google "sorry/index" consent+captcha ("unusual traffic from your computer")
- Generic captcha (hCaptcha, reCAPTCHA iframes)
- Login/account walls where an answer should be

A detected block raises `BlockedError`, which the Mode B job records as a new
`ResultStatus.blocked` — reported separately in run counts (`blocked: N`) and
rendered distinctly on the dashboard. Blocked results are **excluded** from
"absent" scoring: a blocked cell is missing data, not a negative signal.

### Layer 1 — Stealth hardening (free)

`engine/retrievers/stealth.py` builds every Playwright context the same way:

- Launch args: `--disable-blink-features=AutomationControlled` and friends.
- A realistic desktop UA + `navigator.webdriver` removed via an init script.
- `locale` and `timezone_id` matched to the request's geo (a Toronto request
  should not present a UTC clock and `en-US` from an Ashburn datacenter).
- Real `Accept-Language`, viewport, and device-scale.

This defeats naive automation detection and costs nothing. It is on by default.

### Layer 2 — Proxy pool (paid; vendor-neutral)

Playwright accepts a proxy per browser context: `{server, username, password}`.
We thread an optional proxy in from config, selected by the request's country so
a location-based run exits from a matching residential IP.

Configuration is a plain proxy URL (or per-country map), so **any** provider
works — Bright Data, Oxylabs, Smartproxy, IPRoyal, a self-hosted gateway.
Rotating providers expose a single gateway host that rotates per connection; we
just point at it. Nothing about the code assumes a vendor.

```
SCRAPE_PROXY_URL=http://user:pass@gateway.provider.com:7777          # default
SCRAPE_PROXY_MAP={"us":"http://...us...","gb":"http://...gb...","ca":"..."}  # per-country
```

Selection order: country-specific entry in the map → default URL → no proxy.

### Layer 3 — Managed browser fallback (paid; vendor-neutral)

When even a residential proxy loses (aggressive captcha on a surface), we hand
the whole session to a managed "scraping browser" that solves challenges and
proxies for us, and drive it over CDP:

```
SCRAPE_CDP_ENDPOINT=wss://brd-customer-...@brd.superproxy.io:9222
```

`stealth.launch_browser()` calls `connect_over_cdp(endpoint)` instead of
launching local Chromium when the endpoint is set — the adapters are unchanged.
Google already has this escape hatch via SerpAPI; this generalizes it to the AI
surfaces.

### What ships now vs. what waits on a vendor

- **Now (no vendor, no cost):** Layer 0 block detection, Layer 1 stealth, and
  the Layer 2/3 *plumbing* (env-gated, off until configured).
- **On the client's proxy credentials:** set `SCRAPE_PROXY_URL` (or the map) and
  location-based capture exits from residential IPs immediately. Set
  `SCRAPE_CDP_ENDPOINT` only if a surface still blocks through the proxy.

---

## Part 2 — Location-based queries

### Model

A tenant has a **location set** (`locations` table). Each location:

| field | meaning |
| --- | --- |
| `label` | human name, e.g. "Toronto — Downtown" |
| `country` (`gl`) | Google country code, also the proxy-selection key |
| `language` (`hl`) | UI language |
| `lat` / `lng` | optional precise geolocation (browser geolocation API) |
| `active` | included in runs |

A tenant with no locations behaves exactly as today: a single implicit location
from `tenants.aio_geo`. This keeps every existing tenant working unchanged.

### Fan-out and volume

Mode B work fans out over **active locations × queries × surfaces**. Location is
carried on each result (`location_label`, plus the geo snapshot in the raw
envelope) so the dashboard can answer "where are we visible?".

Volume is the cost lever, and it multiplies fast:

```
scrapes = queries × surfaces × locations
runtime ≈ scrapes ÷ rate_per_min      (default 4/min per surface, sequential)
```

50 queries × 3 surfaces × 1 location = 150 scrapes ≈ 40 min.
50 queries × 3 surfaces × 6 locations = 900 scrapes ≈ 4 h.

So multi-location is **plan-gated and capped**:

- `PlanLimits.max_locations` (monitor/diagnose = 1; command = few; custom =
  uncapped). Active locations beyond the cap are truncated, deterministically.
- Location fan-out applies to Mode B surfaces only (the API surfaces measure
  model/knowledge, which isn't location-bound in the same way; AIO already
  takes geo).

### Reads

Result rows gain a `location_label`; a new dashboard slice (future increment)
groups presence/answer-share by location. The Access Audit and Power Pages
layers are location-agnostic and unaffected.

---

## Governance & safety

- Proxying and managed browsers are **operational infrastructure**, not new data
  surfaces — no change to the §4 model allowlist or §8 approval gate.
- Rate limits are unchanged and still per-surface; more locations mean more
  sequential work, never more concurrency against a surface.
- Secrets (`SCRAPE_PROXY_URL`, `SCRAPE_PROXY_MAP`, `SCRAPE_CDP_ENDPOINT`) are
  `sync:false` on the worker only — never committed, mirrored on the API only if
  a future admin UI edits them.

## Decisions for the engagement

1. **Proxy vendor & budget.** The code is vendor-neutral; pick a residential
   provider and a monthly cap. Residential geo-targeting is what makes
   location-based capture real, so this is the one required purchase.
2. **Location list & cadence.** Which cities/countries, and how often. Volume
   (and cost) scale linearly with locations — a weekly multi-location sweep is
   usually the right cadence, not daily.
