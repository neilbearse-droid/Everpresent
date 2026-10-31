"""AI-crawler access audit (§focus-group #1).

A startling share of "the AIs never cite us" cases are self-inflicted: a
robots.txt line or a CDN bot-protection default silently blocks the AI
crawlers, and no amount of content work can fix what the engines can't fetch.
This audit probes a domain the way the engines do:

- robots.txt evaluated per AI agent (retrieval agents vs training agents —
  blocking retrieval removes you from live-search answers TODAY; blocking
  training erodes model knowledge over years),
- a user-agent A/B on the homepage (browser UA vs each search crawler's UA,
  plus GPTBot as a training-only check) to catch CDN-level bot rules that
  robots.txt never shows. Since Cloudflare's 15 Sept 2026 defaults, training
  and agent crawlers are blocked by default on ad-supported sites while search
  crawlers are allowed, so only a refused SEARCH crawler is a visibility hole;
  a GPTBot 403 next to a browser 200 is now the norm,
- llms.txt presence and JSON-LD structured data on the homepage (advisory).

Pure evaluation logic is separated from fetching so it stays fixture-tested;
only audit_domain/audit_domains touch the network.
"""

from typing import Any
from urllib import robotparser

import httpx

from engine.audit.rendering import render_verdict
from engine.netguard import guard_public_request

# (agent, what it powers, kind). Three functional classes (§AEO-plan m2):
#  - training: feeds the next model's parametric layer — blocking is a slow,
#    multi-year knowledge leak (blocking GPTBot has no measured Google effect).
#  - search_index: feeds live retrieval — blocking OAI-SearchBot removes you
#    from ChatGPT search answers entirely, today.
#  - user_fetch: retrieves a page because a conversation referenced it — the
#    closest thing to an "AI impression" in your logs.
# Blocking either live class (search_index / user_fetch) is an immediate
# visibility hole; blocking training is a slow leak.
AI_AGENTS: list[tuple[str, str, str]] = [
    ("GPTBot", "ChatGPT — model training", "training"),
    ("OAI-SearchBot", "ChatGPT — search index", "search_index"),
    ("ChatGPT-User", "ChatGPT — live page fetch", "user_fetch"),
    ("PerplexityBot", "Perplexity — search index", "search_index"),
    ("Perplexity-User", "Perplexity — live page fetch", "user_fetch"),
    ("ClaudeBot", "Claude — model training", "training"),
    ("Claude-SearchBot", "Claude — search index", "search_index"),
    ("Claude-User", "Claude — live page fetch", "user_fetch"),
    ("Googlebot", "Google Search, AI Overviews, AI Mode — index", "search_index"),
    ("Google-Extended", "Gemini / AI Overviews — training", "training"),
    ("Bingbot", "Copilot — search index", "search_index"),
    ("meta-webindexer", "Meta AI — search index", "search_index"),
    ("Meta-ExternalFetcher", "Meta AI — live page fetch", "user_fetch"),
    ("Meta-ExternalAgent", "Meta AI — training", "training"),
    ("Bytespider", "ByteDance / TikTok — training", "training"),
    ("CCBot", "Common Crawl — many models' training", "training"),
]

# The two live-answer classes: blocking either removes you from answers NOW.
_LIVE_KINDS = {"search_index", "user_fetch"}

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# The homepage is fetched once per entry (agent, UA string, kind). The
# search-class bots decide live visibility. GPTBot stays as a training-only
# check: Cloudflare has refused it by default since 15 Sept 2026, so a 403 for
# it says nothing about OAI-SearchBot, PerplexityBot, Claude-SearchBot or bingbot.
UA_PROBES: list[tuple[str, str, str]] = [
    ("OAI-SearchBot",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
     "OAI-SearchBot/1.0; +https://openai.com/searchbot", "search_index"),
    ("PerplexityBot",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
     "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)", "search_index"),
    ("Claude-SearchBot",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
     "Claude-SearchBot/1.0; +Claude-SearchBot@anthropic.com)", "search_index"),
    ("bingbot",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; "
     "bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36",
     "search_index"),
    ("GPTBot",
     "Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.2; +https://openai.com/gptbot)",
     "training"),
]
_BLOCKED_STATUSES = {401, 403, 429}
MAX_HTML_BYTES = 1_500_000  # bound the homepage read; a page, not a tarpit


def entity_signals(html: str) -> dict[str, Any]:
    """Entity-authority signals on the homepage (§AEO-plan m5, Pillar C): the
    machine-readable identity cues engines use to disambiguate the brand as a
    known entity — sameAs links, Organization schema, and Wikipedia/Wikidata
    presence. Pure string inspection."""
    lower = html.lower()
    return {
        "has_sameas": '"sameas"' in lower,
        "has_org_schema": '"organization"' in lower and "application/ld+json" in lower,
        "links_wikipedia": "wikipedia.org" in lower,
        "links_wikidata": "wikidata.org" in lower,
    }


def evaluate_robots(robots_text: str) -> list[dict[str, Any]]:
    """Per-AI-agent verdicts for a robots.txt body. `mentioned` distinguishes
    an explicit rule from falling through to the * group."""
    parser = robotparser.RobotFileParser()
    parser.parse(robots_text.splitlines())
    lower = robots_text.lower()
    return [
        {
            "agent": agent,
            "role": role,
            "kind": kind,
            # Homepage only: a path rule such as "Disallow: /pricing/" for a
            # search bot is not seen here.
            "allowed": parser.can_fetch(agent, "/"),
            "mentioned": agent.lower() in lower,
        }
        for agent, role, kind in AI_AGENTS
    ]


def ua_verdicts(
    status_normal: int | None, bot_statuses: dict[str, int | None]
) -> list[dict[str, Any]]:
    """Per-bot result of the user-agent A/B. A bot is `blocked` when the
    browser got the page but that user agent got a refusal (401/403/429) or
    no response at all (a hard reset for bot UAs is itself a block signal)."""
    browser_ok = status_normal is not None and status_normal < 400
    out = []
    for agent, _ua, kind in UA_PROBES:
        status = bot_statuses.get(agent)
        out.append({
            "agent": agent,
            "kind": kind,
            "status": status,
            "blocked": browser_ok and (status is None or status in _BLOCKED_STATUSES),
        })
    return out


def _name_probes(probes: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{p['agent']} ({p['status'] if p['status'] is not None else 'no response'})"
        for p in probes
    )


def summarize(
    agents: list[dict[str, Any]],
    *,
    ua_probes: list[dict[str, Any]] | None = None,
    has_llms_txt: bool,
    has_json_ld: bool,
    robots_status: int | None,
    render_verdict: str = "pass",
    render_reason: str = "",
    entity: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Grade + human-readable issues. fail = something is blocking live
    retrieval right now (robots block, a CDN refusing a search crawler, or a
    JS-only page engines can't render); warn = training leaks or thin raw
    HTML. JSON-LD and entity signals are advisory and never move the grade."""
    issues: list[str] = []
    retrieval_blocked = [a for a in agents if a["kind"] in _LIVE_KINDS and not a["allowed"]]
    training_blocked = [a for a in agents if a["kind"] == "training" and not a["allowed"]]
    probes = ua_probes or []
    search_refused = [p for p in probes if p["blocked"] and p["kind"] in _LIVE_KINDS]
    training_refused = [p for p in probes if p["blocked"] and p["kind"] == "training"]

    for a in retrieval_blocked:
        issues.append(
            f"robots.txt blocks {a['agent']} ({a['role']}) — you are invisible to its "
            f"live answers until this is removed"
        )
    if search_refused:
        issues.append(
            "The server answers a normal browser but refuses "
            f"{_name_probes(search_refused)} by user agent, so those engines can't read "
            "the site even where robots.txt allows them. Cloudflare's September 2026 "
            "defaults allow search crawlers; a refusal like this usually means a custom "
            "WAF rule or a pre-July 'block all AI' toggle."
        )
    # M3: a JS-only page is as invisible as a hard block — no major AI crawler
    # runs JavaScript, so a CSR shell is a blank page to them.
    if render_verdict == "fail" and render_reason:
        issues.append(render_reason)
    for a in training_blocked:
        issues.append(
            f"robots.txt blocks {a['agent']} ({a['role']}) — future model versions "
            f"won't know the site (slow knowledge leak)"
        )
    if training_refused and not search_refused:
        issues.append(
            f"The server refuses {_name_probes(training_refused)} by user agent while the "
            "search crawlers get through. That is a training-only block, Cloudflare's "
            "default since September 2026: it costs nothing in live answers; future "
            "model versions won't learn the site from it (slow knowledge leak)."
        )
    if robots_status is not None and robots_status >= 500:
        issues.append(f"robots.txt returns HTTP {robots_status} — crawlers may treat the "
                      f"whole site as off-limits")
    if render_verdict == "warn" and render_reason:
        issues.append(render_reason)
    # Advisory: a 2026 quasi-experiment found no citation effect from schema.
    if not has_json_ld:
        issues.append("No JSON-LD on the homepage. It may help Google identify the brand as "
                      "an entity; studies in 2026 found no effect on AI citations.")
    # Entity authority (§AEO-plan m5, Pillar C): advisory, not graded.
    if entity is not None and not (entity.get("has_sameas") or entity.get("links_wikipedia")):
        issues.append("No entity-authority signals on the homepage (sameAs links, "
                      "Wikipedia/Wikidata presence) — engines use these to recognize the "
                      "brand as a known entity")
    # llms.txt is deliberately NOT an issue: 2026 log studies observe zero AI
    # crawler consumption of it, so its absence is not a defect. The frontend
    # still shows a neutral presence chip.

    if retrieval_blocked or search_refused or render_verdict == "fail":
        grade = "fail"
    elif training_blocked or training_refused or render_verdict == "warn":
        grade = "warn"
    else:
        grade = "pass"
    return grade, issues


def audit_domain(client: httpx.Client, domain: str) -> dict[str, Any]:
    base = f"https://{domain.strip().strip('/')}"
    out: dict[str, Any] = {"domain": domain, "error": None}

    robots_status: int | None = None
    agents: list[dict[str, Any]] = []
    try:
        resp = client.get(f"{base}/robots.txt", headers={"User-Agent": BROWSER_UA})
        robots_status = resp.status_code
        # A missing robots.txt (404) means everything is allowed — evaluate "".
        agents = evaluate_robots(resp.text if resp.status_code == 200 else "")
    except httpx.HTTPError as exc:
        out["error"] = f"robots.txt unreachable: {type(exc).__name__}"
        agents = evaluate_robots("")

    has_llms_txt = False
    try:
        resp = client.get(f"{base}/llms.txt", headers={"User-Agent": BROWSER_UA})
        has_llms_txt = (
            resp.status_code == 200 and "<html" not in resp.text[:300].lower()
        )
    except httpx.HTTPError:
        pass

    status_normal: int | None = None
    has_json_ld = False
    rendering: dict[str, Any] = {"verdict": "pass", "word_count": 0, "reason": "", "signals": {}}
    entity: dict[str, Any] = {"has_sameas": False, "has_org_schema": False,
                              "links_wikipedia": False, "links_wikidata": False}
    try:
        resp = client.get(base, headers={"User-Agent": BROWSER_UA})
        status_normal = resp.status_code
        homepage_html = resp.text[:MAX_HTML_BYTES]
        has_json_ld = "application/ld+json" in homepage_html.lower()
        # M3: grade the raw HTML the way non-rendering AI crawlers see it.
        if status_normal < 400:
            rendering = render_verdict(homepage_html)
            entity = entity_signals(homepage_html)
    except httpx.HTTPError as exc:
        out["error"] = out["error"] or f"homepage unreachable: {type(exc).__name__}"
    # One homepage fetch per probed user agent.
    bot_statuses: dict[str, int | None] = {}
    for agent, ua, _kind in UA_PROBES:
        try:
            bot_statuses[agent] = client.get(base, headers={"User-Agent": ua}).status_code
        except httpx.HTTPError:
            bot_statuses[agent] = None  # hard reset for bot UAs is itself a block signal
    ua_probes = ua_verdicts(status_normal, bot_statuses)
    # ua_blocked keeps its old name but now means "a SEARCH crawler is refused".
    ua_blocked = any(p["blocked"] and p["kind"] in _LIVE_KINDS for p in ua_probes)

    grade, issues = summarize(
        agents,
        ua_probes=ua_probes,
        has_llms_txt=has_llms_txt,
        has_json_ld=has_json_ld,
        robots_status=robots_status,
        render_verdict=rendering["verdict"],
        render_reason=rendering["reason"],
        entity=entity,
    )
    out.update(
        robots_status=robots_status,
        agents=agents,
        has_llms_txt=has_llms_txt,
        has_json_ld=has_json_ld,
        status_normal=status_normal,
        status_bot=bot_statuses.get("GPTBot"),  # the training-only probe
        ua_blocked=ua_blocked,
        ua_probes=ua_probes,
        rendering=rendering,
        entity=entity,
        grade=grade,
        issues=issues,
    )
    return out


def audit_domains(domains: list[str], *, timeout_s: float = 8.0) -> list[dict[str, Any]]:
    with httpx.Client(
        timeout=timeout_s, follow_redirects=True,
        event_hooks={"request": [guard_public_request]},
    ) as client:
        return [audit_domain(client, d) for d in domains]
