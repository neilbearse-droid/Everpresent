"""AI-crawler access audit (§focus-group #1).

A startling share of "the AIs never cite us" cases are self-inflicted: a
robots.txt line or a CDN bot-protection default silently blocks the AI
crawlers, and no amount of content work can fix what the engines can't fetch.
This audit probes a domain the way the engines do:

- robots.txt evaluated per AI agent (retrieval agents vs training agents —
  blocking retrieval removes you from live-search answers TODAY; blocking
  training erodes model knowledge over years),
- a user-agent A/B on the homepage (browser UA vs GPTBot UA) to catch
  CDN-level bot challenges that robots.txt never shows,
- llms.txt presence and JSON-LD structured data on the homepage.

Pure evaluation logic is separated from fetching so it stays fixture-tested;
only audit_domain/audit_domains touch the network.
"""

from typing import Any
from urllib import robotparser

import httpx

# (agent, what it powers, kind). Retrieval agents fetch for live answers —
# blocking one is an immediate visibility hole; training agents feed future
# model knowledge — blocking one is a slow leak.
AI_AGENTS: list[tuple[str, str, str]] = [
    ("GPTBot", "ChatGPT — model training", "training"),
    ("OAI-SearchBot", "ChatGPT — search index", "retrieval"),
    ("ChatGPT-User", "ChatGPT — live page fetch", "retrieval"),
    ("PerplexityBot", "Perplexity — search index", "retrieval"),
    ("Perplexity-User", "Perplexity — live page fetch", "retrieval"),
    ("ClaudeBot", "Claude — model training", "training"),
    ("Claude-User", "Claude — live page fetch", "retrieval"),
    ("Google-Extended", "Gemini / AI Overviews — training", "training"),
    ("Bingbot", "Copilot — retrieval", "retrieval"),
    ("CCBot", "Common Crawl — many models' training", "training"),
]

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
GPTBOT_UA = "Mozilla/5.0 AppleWebKit/537.36 (compatible; GPTBot/1.2; +https://openai.com/gptbot)"
_BLOCKED_STATUSES = {401, 403, 429}


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
            "allowed": parser.can_fetch(agent, "/"),
            "mentioned": agent.lower() in lower,
        }
        for agent, role, kind in AI_AGENTS
    ]


def summarize(
    agents: list[dict[str, Any]],
    *,
    ua_blocked: bool,
    has_llms_txt: bool,
    has_json_ld: bool,
    robots_status: int | None,
) -> tuple[str, list[str]]:
    """Grade + human-readable issues. fail = something is blocking live
    retrieval right now; warn = training leaks or missing best practices."""
    issues: list[str] = []
    retrieval_blocked = [a for a in agents if a["kind"] == "retrieval" and not a["allowed"]]
    training_blocked = [a for a in agents if a["kind"] == "training" and not a["allowed"]]

    for a in retrieval_blocked:
        issues.append(
            f"robots.txt blocks {a['agent']} ({a['role']}) — you are invisible to its "
            f"live answers until this is removed"
        )
    if ua_blocked:
        issues.append(
            "The server answers a normal browser but rejects an AI-crawler user agent — "
            "likely CDN bot protection (e.g. a 'block AI bots' default). Engines can't "
            "read the site even where robots.txt allows them."
        )
    for a in training_blocked:
        issues.append(
            f"robots.txt blocks {a['agent']} ({a['role']}) — future model versions "
            f"won't know the site (slow knowledge leak)"
        )
    if robots_status is not None and robots_status >= 500:
        issues.append(f"robots.txt returns HTTP {robots_status} — crawlers may treat the "
                      f"whole site as off-limits")
    if not has_llms_txt:
        issues.append("No llms.txt — an easy, emerging way to guide AI crawlers to your "
                      "canonical pages")
    if not has_json_ld:
        issues.append("No JSON-LD structured data detected on the homepage — engines lean "
                      "on schema to extract citable facts")

    if retrieval_blocked or ua_blocked:
        grade = "fail"
    elif training_blocked or not has_llms_txt or not has_json_ld:
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
    status_bot: int | None = None
    has_json_ld = False
    try:
        resp = client.get(base, headers={"User-Agent": BROWSER_UA})
        status_normal = resp.status_code
        has_json_ld = "application/ld+json" in resp.text.lower()
    except httpx.HTTPError as exc:
        out["error"] = out["error"] or f"homepage unreachable: {type(exc).__name__}"
    try:
        resp = client.get(base, headers={"User-Agent": GPTBOT_UA})
        status_bot = resp.status_code
    except httpx.HTTPError:
        status_bot = None  # hard reset for bot UAs is itself a block signal

    ua_blocked = (
        status_normal is not None
        and status_normal < 400
        and (status_bot is None or status_bot in _BLOCKED_STATUSES)
    )

    grade, issues = summarize(
        agents,
        ua_blocked=ua_blocked,
        has_llms_txt=has_llms_txt,
        has_json_ld=has_json_ld,
        robots_status=robots_status,
    )
    out.update(
        robots_status=robots_status,
        agents=agents,
        has_llms_txt=has_llms_txt,
        has_json_ld=has_json_ld,
        status_normal=status_normal,
        status_bot=status_bot,
        ua_blocked=ua_blocked,
        grade=grade,
        issues=issues,
    )
    return out


def audit_domains(domains: list[str], *, timeout_s: float = 8.0) -> list[dict[str, Any]]:
    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        return [audit_domain(client, d) for d in domains]
