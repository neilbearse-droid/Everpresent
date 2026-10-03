"""The recommendations playbook: one ranked to-do list built from every
signal EverPresent measures, each play specific to the tenant's own data and
graded by how strong the evidence behind it is (as of October 2026).

Sources, in rough priority order:
  accuracy        engines state a wrong fact → fix the cited source
  crawler_access  an AI search bot can't reach the site (Agent Analytics)
  refresh         a brand page lost its citation run over run
  broken_page     AI bots keep requesting pages that error
  reviews/earned/community/reference
                  third-party pages that cite rivals but not you, grouped by
                  the kind of source (each needs a different play)
  subquery        fan-out searches the engines run where you're absent
  web_search/training/aio
                  the original §6.4 per-query gap matrix, now with the rivals,
                  sources and sub-questions for that query
  read_not_cited  pages AI search reads but never cites
  strategy        one pinned play: what to focus on given how often you're named

Regeneration is idempotent: gap_ref is stable, a human's status is kept, the
text and priority refresh to the latest data, closed gaps auto-resolve, and
reopened gaps come back."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from api.models import (
    AccuracyFinding,
    Citation,
    FanoutShard,
    Mention,
    Query,
    QueryClassification,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    SurfaceCode,
    Tenant,
    utcnow,
)

log = logging.getLogger(__name__)

HAND_STATUSES = {RecommendationStatus.done, RecommendationStatus.dismissed}


@dataclass
class Play:
    gap_ref: str
    branch: str
    title: str
    action_text: str
    priority: int
    evidence: str  # official | strong | moderate | emerging
    why: str
    steps: list[str] = field(default_factory=list)
    query_text: str = ""
    link: str = ""


# Evidence statements, one per kind of play. Kept here so every play of a kind
# cites the same, dated, honestly-graded finding.
WHY = {
    "subquery": (
        "Engines answer by running several sub-searches (Gemini 3 averages ~10.7 per "
        "prompt), and only ~38% of AI Overview citations rank in Google's top 10 for the "
        "main query. Pages that rank for the sub-searches were 161% more likely to be "
        "cited (Seer, Ahrefs, Surfer; 2026)."
    ),
    "facts": (
        "In a 252,000-trial controlled study across six models (2026), topical relevance, "
        "explicit prices and recent dates raised citation odds; formatting alone did not."
    ),
    "earned": (
        "AI search draws most citations from third-party sources: 82% earned media in "
        "one 2025 audit versus 45% for Google search."
    ),
    "reviews": (
        "In a 2026 controlled test, a rival's rating lead of under 0.1 stars erased a "
        "well-known brand's advantage. Brands with active review profiles were cited far "
        "more often in an 800K-answer study (sponsored, correlational)."
    ),
    "community": (
        "Reddit, YouTube and forums are among the most-cited domains in Perplexity and "
        "Google's AI answers (Semrush, Search Engine Land; 2026). Evidence is "
        "correlational; astroturfing gets removed and can backfire."
    ),
    "reference": (
        "Wikipedia is ChatGPT's single most-cited domain (~7.8% of citations, 2026), and "
        "reference entries feed both live answers and future training data."
    ),
    "accuracy": (
        "Most wrong facts in search-backed answers trace to a wrong or stale page the "
        "engine cited, not to the model itself (vendor analysis, 2026). Fix the source, "
        "trigger a recrawl, and re-check over several runs."
    ),
    "crawler": (
        "Official: ChatGPT search only shows sites OAI-SearchBot can crawl; Copilot and "
        "ChatGPT lean on Bing's index; Google's AI features need normal Googlebot "
        "indexing. A blocked bot means zero chance on that engine."
    ),
    "refresh": (
        "Cited pages skew fresh: 72% had been updated in the past year (Seer, 2026). "
        "Losing a citation is the earliest decay signal, and a refresh is cheap."
    ),
    "broken": (
        "Bots that hit errors drop or downgrade pages; a cited URL that 404s can't be "
        "cited again until it's fixed or redirected."
    ),
    "read_not_cited": (
        "AI search is reading these pages and choosing other sources: they're retrieved "
        "but lose on evidence. That's the cheapest gap to close (2026 absorption study)."
    ),
    "training": (
        "Answers from model memory change only when a new model is trained. Brands with "
        "strong third-party coverage are named more; there's no fast lever here."
    ),
    "aio": (
        "Google says AI Overviews and AI Mode need no special markup, just indexable, "
        "snippet-eligible pages (official, 2026). They cite mostly pages that answer the "
        "sub-searches, many outside the top 10."
    ),
    "logs": (
        "Only server logs show whether ChatGPT, Perplexity, Claude and Google's AI bots "
        "can actually reach your pages, and which pages they read."
    ),
    "strategy": (
        "A 37,000-run 2026 audit found ~half of specialist brands never surfaced, while "
        "mid-market brands surfaced but were rarely recommended; leading brands faced "
        "more fabricated facts. The right play depends on where you start."
    ),
}

_RECRAWL = (
    "Request a recrawl after the change: IndexNow (Bing, which feeds Copilot and "
    "ChatGPT) and URL Inspection in Google Search Console"
)


def _join(items: list[str], n: int = 3) -> str:
    items = [i for i in items if i][:n]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _action_text(branch: str, query_text: str) -> str:
    """Fallback text for a per-query gap with no richer context."""
    if branch == "web_search":
        return (
            f'AI answers for "{query_text}" use live web search and don\'t name you. '
            "Answer the query and its sub-questions directly, with explicit facts, and get "
            "onto the third-party pages those answers already cite."
        )
    if branch == "training":
        return (
            f'AI answers for "{query_text}" come from model memory, not live search. '
            "Build durable third-party coverage (reviews, reference entries, press) so "
            "future models learn the brand."
        )
    return (
        f'Google\'s AI Overview answers "{query_text}" without citing you. Answer the '
        "sub-questions it searches, and get onto the domains it already cites."
    )


def _query_gaps(
    session: Session, tenant_id: int
) -> dict[tuple[str, str], dict[str, list[str]]]:
    """The §6.4 matrix: (query_text, branch) gaps from the latest answers,
    each with the engines that name the brand and the ones that don't."""

    # Gaps are a competitive concept — a branded query where the brand always
    # appears has no "visibility gap". Only non-branded queries generate
    # recommendations (branded ones live in the Brand-knowledge layer).
    queries = session.exec(
        select(Query).where(
            Query.tenant_id == tenant_id,
            Query.active == True,  # noqa: E712
            Query.branded == False,  # noqa: E712
        )
    ).all()
    # A query is classified per (query_text, surface); collapse to one row per
    # query DETERMINISTICALLY (lowest surface code wins) rather than last-wins
    # over an unordered result set, so the web_search-vs-training branch a query
    # takes doesn't flip between runs (§audit low).
    # Prefer a row that actually has a web-search classification (the AIO
    # pass can create placeholder rows with an empty one), then the lowest
    # surface code as TEXT — Postgres orders a native enum by declaration
    # order, which would pick a different row than SQLite.
    classifications: dict[str, QueryClassification] = {}
    rows = session.exec(
        select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
    ).all()
    for c in sorted(rows, key=lambda r: (not r.web_search_likelihood, str(r.surface))):
        classifications.setdefault(c.query_text, c)

    # Every ok search answer from the LATEST run that measured each
    # (query_text, surface) — all personas and locations of that run, not one
    # arbitrary row — so "the brand never shows up" means none of them named it.
    by_key: dict[tuple[str, str], list[Result]] = {}
    for result in session.exec(
        select(Result).where(
            Result.tenant_id == tenant_id,
            Result.variant == ResultVariant.search,
        )
    ).all():
        if result.status != ResultStatus.ok:
            continue
        by_key.setdefault((result.query_text, str(result.surface)), []).append(result)
    latest: dict[tuple[str, str], list[Result]] = {}
    for key, rows_for_key in by_key.items():
        newest_run = max(r.run_id for r in rows_for_key)
        latest[key] = [r for r in rows_for_key if r.run_id == newest_run]
    latest_ids = [r.id for rs in latest.values() for r in rs if r.id is not None]
    brand_mentioned_ids: set[int] = set()
    if latest_ids:
        for mention in session.exec(
            select(Mention).where(
                Mention.result_id.in_(latest_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            brand_mentioned_ids.add(mention.result_id)

    from api.models import BrandProfile
    from engine.processing.citations import domain_is_owned

    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    brand_domains = brand.domains if brand else []

    # Which (query, branch) gaps exist right now, with the engines that name
    # the brand and the ones that don't?
    active_gaps: dict[tuple[str, str], dict[str, list[str]]] = {}
    for query in queries:
        results_for_query = [
            r for (q_text, _s), rs in latest.items() if q_text == query.text for r in rs
        ]
        # Answer-surface gap: measured, and the brand is named on fewer than a
        # third of the engines (missing on 8 of 9 is a gap, not a win).
        answer_results = [
            r for r in results_for_query if r.surface != SurfaceCode.google_aio
        ]
        measured = {str(r.surface) for r in answer_results}
        named = {str(r.surface) for r in answer_results if r.id in brand_mentioned_ids}
        answer_gap = bool(measured) and len(named) * 3 < len(measured)
        presence = {"named": sorted(named), "missing": sorted(measured - named)}
        classification = classifications.get(query.text)
        if answer_gap and classification and classification.web_search_likelihood:
            if classification.web_search_likelihood in ("very_likely", "likely"):
                active_gaps[(query.text, "web_search")] = presence
            elif classification.web_search_likelihood == "unlikely":
                active_gaps[(query.text, "training")] = presence
            # "possible" is ambiguous — no prescription (§6.4 matrix maps
            # clear classifications only).

        # AIO branch: the Overview dominates and cites none of our domains.
        if classification and classification.google_aio_source_type in (
            "aio_dominant",
            "aio_plus_organic",
        ):
            cited = classification.google_aio_signals.get("cited_domains", [])
            if not any(domain_is_owned(d, brand_domains) for d in cited):
                active_gaps[(query.text, "aio")] = presence

    return active_gaps


# ---------------------------------------------------------------- plays ----

_CHATGPT_SURFACES = {"openai_api", "chatgpt_web"}


def _query_context(session: Session, tenant_id: int) -> dict[str, dict]:
    """Per query, from the latest answers: the rivals named most, the
    third-party domains cited most, and the fan-out sub-questions where the
    brand is absent. Makes every per-query play name names."""
    from api.dashboards_service import _latest_results_by_variant, _owned_domains
    from engine.processing.citations import domain_is_owned

    latest = _latest_results_by_variant(session, tenant_id, ResultVariant.search,
                                        scope="competitive")
    q_of = {r.id: r.query_text for r in latest.values() if r.id is not None}
    ctx: dict[str, dict] = {}

    def entry(q: str) -> dict:
        return ctx.setdefault(q, {"rivals": {}, "sources": {}, "subs": []})

    if q_of:
        for rid, name, etype in session.exec(
            select(col(Mention.result_id), col(Mention.entity_name), col(Mention.entity_type))
            .where(col(Mention.result_id).in_(list(q_of)))
        ).all():
            if etype != "brand":
                r = entry(q_of[rid])["rivals"]
                r[name] = r.get(name, 0) + 1
        owned = _owned_domains(session, tenant_id)
        for rid, domain, cat in session.exec(
            select(col(Citation.result_id), col(Citation.domain),
                   col(Citation.source_category))
            .where(col(Citation.result_id).in_(list(q_of)))
        ).all():
            if cat == "other" and domain and not domain_is_owned(domain, owned):
                src = entry(q_of[rid])["sources"]
                src[domain] = src.get(domain, 0) + 1
    last = session.exec(
        select(col(FanoutShard.run_id)).where(FanoutShard.tenant_id == tenant_id)
        .order_by(col(FanoutShard.run_id).desc()).limit(1)
    ).first()
    if last is not None:
        for sh in sorted(
            session.exec(select(FanoutShard).where(
                FanoutShard.tenant_id == tenant_id, FanoutShard.run_id == last,
                FanoutShard.brand_present != True,  # noqa: E712
            )).all(),
            key=lambda x: -x.reach,
        ):
            entry(sh.parent_query_text)["subs"].append(sh.shard_text)

    def top(d: dict[str, int]) -> list[str]:
        return [k for k, _n in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {q: {"rivals": top(e["rivals"]), "sources": top(e["sources"]), "subs": e["subs"]}
            for q, e in ctx.items()}


def _query_plays(session: Session, tenant_id: int, plan: dict) -> list[Play]:
    briefs = {b["query"]: b for b in plan.get("briefs", [])}
    context = _query_context(session, tenant_id)
    aio_cited: dict[str, list[str]] = {}
    for c in session.exec(
        select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
    ).all():
        cited = (c.google_aio_signals or {}).get("cited_domains") or []
        if cited:
            aio_cited[c.query_text] = list(cited)
    plays: list[Play] = []
    from api.dashboards_service import _surface_label

    gaps = _query_gaps(session, tenant_id)
    for (query_text, branch), presence in sorted(gaps.items()):
        missing = [_surface_label(x) for x in presence["missing"]]
        named_on = [_surface_label(x) for x in presence["named"]]
        where = (f" You're named on {_join(named_on, 4)} but missing on {_join(missing, 4)}."
                 if named_on else "")
        b = briefs.get(query_text) or {}
        c = context.get(query_text) or {}
        rivals = b.get("competitors_winning") or c.get("rivals") or []
        sources = [t["domain"] for t in b.get("target_sources") or []] or c.get("sources") or []
        subs = c.get("subs") or b.get("subtopics") or []
        contest = (b.get("contestability") or {}).get("label", "needs history")
        ref = f"query:{query_text}::branch:{branch}"
        if branch == "web_search":
            priority = 60 + {"winnable now": 20, "contested": 8, "locked in": -15}.get(contest, 0)
            text = f'AI answers for "{query_text}" use live search and mostly leave you out'
            text += f"; {_join(rivals)} show up instead." if rivals else "."
            text += where
            steps = []
            if subs:
                steps.append(f"Answer the sub-questions engines search: {_join(subs, 4)}")
            steps.append("State prices, plans, limits and dates as plain text on that page")
            if sources:
                steps.append(f"Get onto the pages these answers already cite: {_join(sources, 4)}")
            if b.get("spam_risk"):
                steps.append("Don't answer it with your own ranked 'best X' list (see Don'ts)")
            steps.append("Log the change in Outcome with an untouched control page, then "
                         "judge it after 2–3 weeks of runs")
            plays.append(Play(ref, branch, f"Win “{query_text}”", text, priority, "strong",
                              WHY["subquery"], steps, query_text, "/dashboard/action-plan"))
        elif branch == "training":
            plays.append(Play(
                ref, branch, f"Long game: “{query_text}”",
                f'Engines answer "{query_text}" from memory and mostly leave you out'
                + (f"; they name {_join(rivals)}." if rivals else ".") + where,
                30, "emerging", WHY["training"],
                ["Earn coverage in sources models learn from: reviews, trade press, "
                 "reference entries",
                 "Make sure your own pages state what you do in plain, quotable sentences",
                 "Expect movement only when a new model version ships"],
                query_text, "/dashboard/action-plan"))
        else:
            cited = [d for d in aio_cited.get(query_text, [])][:4]
            steps = []
            if subs:
                steps.append(f"Cover the sub-questions Google searches: {_join(subs, 4)}")
            if cited:
                steps.append(f"Get onto the domains the Overview cites now: {_join(cited, 4)}")
            steps += ["Check the page is indexed and snippet-eligible (no nosnippet, "
                      "content in HTML, not only in scripts)",
                      "Skip special AI markup: Google says none is needed"]
            plays.append(Play(
                ref, branch, f"Get cited in Google's AI answer for “{query_text}”",
                f'Google\'s AI Overview answers "{query_text}" without citing you.',
                55, "official", WHY["aio"], steps, query_text, "/dashboard/action-plan"))
    return plays


def _accuracy_plays(session: Session, tenant_id: int) -> list[Play]:
    from api.dashboards_service import _latest_results_by_variant, _surface_label

    latest = _latest_results_by_variant(session, tenant_id, ResultVariant.search)
    by_id = {r.id: r for r in latest.values() if r.id is not None}
    if not by_id:
        return []
    # One play per fact, however differently the engines word the wrong value.
    groups: dict[int, dict] = {}
    for f in session.exec(
        select(AccuracyFinding).where(
            AccuracyFinding.tenant_id == tenant_id,
            col(AccuracyFinding.result_id).in_(list(by_id)),
        ).order_by(col(AccuracyFinding.id))
    ).all():
        g = groups.setdefault(f.fact_id, {"f": f, "results": set(), "stated": []})
        g["results"].add(f.result_id)
        if f.stated not in g["stated"]:
            g["stated"].append(f.stated)
    plays = []
    for fact_id, g in sorted(groups.items()):
        f = g["f"]
        stated = " / ".join(g["stated"][:3])
        rids = sorted(g["results"])
        engines = sorted({_surface_label(str(by_id[r].surface)) for r in rids})
        urls: dict[str, int] = {}
        for url in session.exec(
            select(col(Citation.url)).where(col(Citation.result_id).in_(rids))
        ).all():
            urls[url] = urls.get(url, 0) + 1
        top = [u for u, _n in sorted(urls.items(), key=lambda kv: (-kv[1], kv[0]))][:4]
        steps = []
        if top:
            steps.append(f"Check the pages those answers cite, and get them corrected: "
                         f"{_join(top, 4)}")
        steps += [f"State the correct {f.subject} ({f.expected}) plainly on your own page, "
                  "with an updated date", _RECRAWL,
                  "Re-check over the next 2–3 runs; memory-based answers may wait for "
                  "the next model version"]
        plays.append(Play(
            f"accuracy:{fact_id}", "accuracy",
            f"Fix a wrong fact: {f.subject}",
            f"{_join(engines, 4)} say {f.subject} is {stated}; it's {f.expected}.",
            98 if len(engines) > 1 else 94, "moderate", WHY["accuracy"], steps,
            link="/dashboard/brand"))
    return plays


# The bots that decide whether an engine can show the site at all.
_KEY_BOTS = {
    "OAI-SearchBot": "ChatGPT search",
    "Bingbot": "Copilot and ChatGPT (Bing's index)",
    "PerplexityBot": "Perplexity",
    "Claude-SearchBot": "Claude",
    "Googlebot": "Google AI Overviews and AI Mode",
}
_MIN_LOG_HITS = 200  # below this, a missing bot is more likely a partial log


def _agent_plays(session: Session, tenant_id: int) -> list[Play]:
    from api.agent_analytics import agent_analytics

    a = agent_analytics(session, tenant_id)
    if not a.get("has_data") and a.get("stale"):
        # Logs were uploaded once but none are recent: ask for fresh logs and
        # leave the existing bot plays as they are (no data isn't "fixed").
        raise _KeepExisting([Play(
            "connect_logs", "connect_logs", "Upload recent server logs",
            f"Your newest AI-bot log data is more than {a['days']} days old, so bot "
            "access and page checks are on hold.",
            40, "official", WHY["logs"],
            ["Upload the last 30 days of access logs on the AI Agents tab, or set up "
             "the automatic push from your CDN so this never goes stale"],
            link="/dashboard/agents")])
    if not a.get("has_data"):
        return [Play(
            "connect_logs", "connect_logs", "Connect your server logs",
            "See which AI bots can reach your site and which pages they read.",
            25, "official", WHY["logs"],
            ["Upload a recent access log on the AI Agents tab, or set up the automatic "
             "push from your CDN"], link="/dashboard/agents")]
    plays: list[Play] = []
    bots = {b["bot"]: b for b in a["by_bot"]}
    if a["total_hits"] >= _MIN_LOG_HITS:
        for bot, engine in _KEY_BOTS.items():
            b = bots.get(bot)
            if b is None:
                plays.append(Play(
                    f"crawler:{bot}:absent", "crawler_access",
                    f"{bot} hasn't visited in {a['days']} days",
                    f"Without {bot}, {engine} can't show your pages.",
                    90, "official", WHY["crawler"],
                    [f"Check robots.txt allows {bot} (you can still block training-only "
                     "bots like GPTBot)",
                     "Check CDN / firewall bot rules (e.g. Cloudflare's AI-bot blocking) "
                     f"aren't stopping {bot}",
                     "Confirm the site is indexed in Bing Webmaster Tools and Google "
                     "Search Console"],
                    link="/dashboard/agents"))
            elif b["hits"] and b.get("blocked", 0) / b["hits"] > 0.2 and b["blocked"] >= 20:
                # Only refusals count (401/403/429/5xx): a 404 is a dead page,
                # handled by the broken-pages play, not the bot being blocked.
                pct = round(100 * b["blocked"] / b["hits"])
                plays.append(Play(
                    f"crawler:{bot}:errors", "crawler_access",
                    f"{bot} is refused on {pct}% of requests",
                    f"{engine} is being turned away from much of your site.",
                    88, "official", WHY["crawler"],
                    ["Check firewall, bot-challenge and rate-limit rules for "
                     f"{bot} (403, 429 and 5xx responses)",
                     "Find the affected pages on the AI Agents tab (Most-read pages)"],
                    link="/dashboard/agents"))
    for p in a.get("cited_at_risk", [])[:5]:
        if "error" in p["reason"]:
            plays.append(Play(
                f"at_risk:{p['path']}", "broken_page",
                f"A cited page is erroring for AI bots: {p['path']}",
                f"AI answers cite {p['path']} ({p['cited']}×), but it returned "
                f"{p['reason']}.",
                86, "strong", WHY["broken"],
                ["Fix the error or 301 it to the live page", _RECRAWL],
                link="/dashboard/agents"))
    broken = a.get("broken_pages", [])[:8]
    if broken:
        total = sum(p["errors"] for p in broken)
        paths = [p["path"] for p in broken]
        plays.append(Play(
            "broken_pages", "broken_page",
            f"Redirect {len(broken)} dead page{'s' if len(broken) != 1 else ''} AI bots "
            "keep requesting",
            f"AI bots got {total:,} errors on {_join(paths, 5)}"
            + (f" and {len(paths) - 5} more" if len(paths) > 5 else "") + ".",
            70, "strong", WHY["broken"],
            ["301 each to the closest live page", "Remove them from sitemaps and internal "
             "links", _RECRAWL], link="/dashboard/agents"))
    rnc = a.get("read_not_cited", [])[:8]
    if rnc:
        paths = [f"{p['path']} ({p['search'] + p['user']:,} reads)" for p in rnc]
        plays.append(Play(
            "read_not_cited", "read_not_cited",
            f"{len(rnc)} page{'s' if len(rnc) != 1 else ''} AI reads but never cites",
            f"AI search keeps fetching {_join(paths, 5)}, but no measured answer cites them.",
            50, "moderate", WHY["read_not_cited"],
            ["Check the content is in the HTML (view it with JavaScript off)",
             "Lead with a direct answer; state prices, dates and specs as text",
             "Make sure each answers the sub-questions engines search for its topic"],
            link="/dashboard/agents"))
    return plays


def _refresh_plays(plan: dict) -> list[Play]:
    plays = []
    for lost in (plan.get("protect") or {}).get("lost", [])[:6]:
        url, queries = lost["url"], lost["queries"]
        plays.append(Play(
            f"refresh:{url}", "refresh", f"Win back a lost citation: {url}",
            f"This page stopped being cited for {_join([f'“{q}”' for q in queries], 3)}.",
            80, "moderate", WHY["refresh"],
            ["Update the numbers, examples and dates; show 'Updated <month year>'",
             "Check it still answers those queries directly, near the top",
             "Check it loads for bots (AI Agents tab)", _RECRAWL],
            link="/dashboard/action-plan"))
    return plays


def _subquery_plays(session: Session, tenant_id: int) -> list[Play]:
    last = session.exec(
        select(col(FanoutShard.run_id)).where(FanoutShard.tenant_id == tenant_id)
        .order_by(col(FanoutShard.run_id).desc()).limit(1)
    ).first()
    if last is None:
        return []
    shards = [s for s in session.exec(
        select(FanoutShard).where(
            FanoutShard.tenant_id == tenant_id, FanoutShard.run_id == last,
            FanoutShard.brand_present == False,  # noqa: E712
        )
    ).all()]
    by_parent: dict[str, list[FanoutShard]] = {}
    for sh in shards:
        by_parent.setdefault(sh.parent_query_text, []).append(sh)
    plays = []
    for parent, group in by_parent.items():
        group.sort(key=lambda x: (-x.reach, x.shard_norm))
        winners = sorted({w for sh in group for w in (sh.winners or [])})
        reach = max(sh.reach for sh in group)
        listed = [f"“{sh.shard_text}”" for sh in group[:5]]
        plays.append(Play(
            f"subquery:{parent}", "subquery",
            f"Cover the sub-questions behind “{parent}”",
            f"To answer “{parent}”, engines also search {_join(listed, 5)}"
            + (f" (and {len(group) - 5} more)" if len(group) > 5 else "")
            + ". You're absent from those results"
            + (f"; {_join(winners)} {'appears' if len(winners) == 1 else 'appear'}."
               if winners else "."),
            min(85, 60 + 6 * reach) if winners else min(75, 55 + 5 * reach),
            "strong", WHY["subquery"],
            ["Answer each sub-question in its own section (or page), first lines under "
             "a clear heading",
             "State the facts they ask about explicitly: numbers, prices, dates",
             "Check which pages rank for them and whether you can be listed there"],
            query_text=parent, link="/dashboard/fanout"))
    plays.sort(key=lambda p: (-p.priority, p.gap_ref))
    return plays[:6]


def _source_plays(plan: dict) -> list[Play]:
    from engine.processing.citations import classify_source_type

    buckets: dict[str, list[dict]] = {}
    for t in plan.get("targets", []):
        # A target: cited alongside rivals at least twice as often as alongside you.
        rival_n, brand_n = t["competitor_assoc"], t.get("brand_assoc", 0)
        if rival_n < 2 or brand_n * 2 > rival_n:
            continue
        kind = classify_source_type(t["domain"])
        kind = {"video": "community", "social": "community",
                "encyclopedia": "reference"}.get(kind, kind)
        buckets.setdefault(kind, []).append(t)
    plays = []
    if buckets.get("review"):
        doms = [t["domain"] for t in buckets["review"]]
        plays.append(Play(
            "sources:review", "reviews", f"Build your review profile on {_join(doms, 3)}",
            f"Answers cite {_join(doms, 4)} when they name rivals, but not you.",
            76, "moderate", WHY["reviews"],
            ["Claim and complete the profile: plans, prices, categories, screenshots",
             "Ask real customers for reviews after a success moment; never tie incentives "
             "to positive reviews (FTC fake-review rule)",
             "Reply to reviews, especially critical ones; keep facts current"],
            link="/dashboard/action-plan"))
    if buckets.get("publisher"):
        doms = [t["domain"] for t in buckets["publisher"]]
        plays.append(Play(
            "sources:publisher", "earned", f"Get onto {_join(doms, 3)}",
            f"These pages are cited alongside rivals for your queries "
            f"({len(doms)} publishers in all). Third-party lists drove ~86% of brand "
            "mentions in a September 2026 test; brands' own lists drove 14%.",
            70, "moderate", WHY["earned"],
            ["Check whether each page lists rivals and not you; pitch an update with "
             "current facts, original data or an expert quote",
             "Disclose any paid placement; undisclosed pay-to-play is a spam risk",
             "Re-check monthly: about half of cited sources rotate out within 30 days"],
            link="/dashboard/action-plan"))
    if buckets.get("community"):
        doms = [t["domain"] for t in buckets["community"]]
        plays.append(Play(
            "sources:community", "community", f"Show up where people discuss: {_join(doms, 3)}",
            f"{_join(doms, 4)} are cited for your queries alongside rivals. These matter "
            "most for Google's AI answers and Perplexity; ChatGPT cut Reddit citations "
            "~86% in August 2026.",
            52, "emerging", WHY["community"],
            ["Answer real threads as a disclosed company account; no sock puppets",
             "On YouTube, publish genuine how-to and comparison videos with clear titles",
             "Prioritize by engine: this play is for Google and Perplexity, not ChatGPT"],
            link="/dashboard/citations"))
    if buckets.get("reference"):
        doms = [t["domain"] for t in buckets["reference"]]
        plays.append(Play(
            "sources:reference", "reference", "Check your reference entries",
            f"{_join(doms)} is cited for your queries alongside rivals.",
            48, "moderate", WHY["reference"],
            ["Check your Wikipedia and Wikidata entries for accuracy and missing facts",
             "Propose fixes on the article's talk page with independent sources; don't "
             "edit your own article or pay for undisclosed edits"],
            link="/dashboard/citations"))
    return plays


def _owned_docs_play(session: Session, tenant_id: int, plan: dict) -> list[Play]:
    """ChatGPT shifted to searching inside brand sites in August 2026; if its
    answers rarely cite the brand's own pages, the help/docs/pricing pages are
    the cheapest lever for that engine."""
    from api.dashboards_service import _latest_results_by_variant

    latest = _latest_results_by_variant(session, tenant_id, ResultVariant.search,
                                        scope="competitive")
    ids = [r.id for r in latest.values()
           if r.id is not None and str(r.surface) in _CHATGPT_SURFACES]
    if not ids:
        return []
    cats = session.exec(
        select(col(Citation.source_category)).where(col(Citation.result_id).in_(ids))
    ).all()
    if len(cats) < 20:
        return []
    share = sum(1 for c in cats if c == "brand") / len(cats)
    if share >= 0.10:
        return []
    return [Play(
        "owned:chatgpt_docs", "owned",
        "Make your help, docs and pricing pages ChatGPT-ready",
        ("None" if share == 0 else f"Only {round(100 * share)}%")
        + " of ChatGPT's citations on your queries point at your own site. Since "
        "August 2026 ChatGPT searches inside brand sites far more "
        "(site: searches rose from 0.4% to ~17%), favouring help centers and docs.",
        72, "moderate",
        "ChatGPT's in-site searches jumped in August 2026 while its Reddit citations fell "
        "~86%; help centers and product docs took the slots (Otterly, Peec; 2026, "
        "vendor data).",
        ["Make sure help-center, docs and pricing pages are public, crawlable HTML",
         "One page per real customer question, answer first, facts explicit",
         "Keep plan names, prices and limits identical across pricing, docs and help"],
        link="/dashboard/citations")]


def _strategy_play(session: Session, tenant_id: int) -> list[Play]:
    from api.dashboards_service import mention_rates

    overall = mention_rates(session, tenant_id).get("overall") or {}
    n, rate = overall.get("answers", 0), overall.get("rate", 0.0)
    if n < 30:
        return []
    if rate < 20:
        title, text, steps = (
            "Focus: get retrieved at all",
            f"You're named in {rate}% of answers on your category queries. Engines aren't "
            "finding you yet, so on-page polish won't move much.",
            ["Prioritize third-party lists, reviews and directories engines already cite",
             "Cover the sub-questions engines search (Fan-out tab)",
             "Make sure every AI search bot can reach the site (AI Agents tab)"])
    elif rate < 70:
        title, text, steps = (
            "Focus: turn mentions into recommendations",
            f"You're named in {rate}% of answers, but naming isn't recommending. The "
            "gap is in how you're positioned for each buyer.",
            ["Check which personas and queries name rivals first (Personas tab)",
             "Publish honest comparisons that say who you're best for",
             "Close rating gaps on the review sites engines cite"])
    else:
        title, text, steps = (
            "Focus: defend accuracy and freshness",
            f"You're named in {rate}% of answers. The risk now is engines getting your "
            "facts wrong or citing stale pages.",
            ["Keep the fact sheet current so accuracy checks catch errors (Brand tab)",
             "Refresh any page that loses a citation within a week",
             "Watch rivals gaining on the queries you lead"])
    return [Play("strategy", "strategy", title, text, 100, "moderate", WHY["strategy"],
                 steps, link="/dashboard")]


class _KeepExisting(Exception):  # noqa: N818 — a signal, not an error
    """Raised by a play source that can't judge its plays right now (data
    missing or stale): its `plays` are added, and the plays it already had
    are left exactly as they are instead of being auto-resolved."""

    def __init__(self, plays: list[Play]) -> None:
        super().__init__("keep existing")
        self.plays = plays


# Which kinds of play each source owns, so a source that failed or can't
# judge leaves its own plays alone.
_SOURCE_BRANCHES = {
    "query": {"web_search", "training", "aio"},
    "accuracy": {"accuracy"},
    "agents": {"crawler_access", "broken_page", "read_not_cited", "connect_logs"},
    "refresh": {"refresh"},
    "subquery": {"subquery"},
    "sources": {"reviews", "earned", "community", "reference"},
    "owned_docs": {"owned"},
    "strategy": {"strategy"},
}


def _run_source(
    session: Session, name: str, fn: Callable[[], list[Play]], frozen: set[str]
) -> list[Play]:
    """Run one play source inside a savepoint. A failure (logged) or a
    _KeepExisting freezes that source's branches: its existing plays keep
    their status instead of being resolved by a missing signal. The savepoint
    keeps a SQL error in one source from aborting the whole transaction."""
    try:
        with session.begin_nested():
            return fn()
    except _KeepExisting as keep:
        frozen.update(_SOURCE_BRANCHES[name])
        return keep.plays
    except Exception:  # noqa: BLE001
        log.exception("recommendations: %s plays failed", name)
        frozen.update(_SOURCE_BRANCHES[name])
        return []


def generate_recommendations(session: Session, tenant: Tenant) -> int:
    """Rebuild the playbook. Returns the number of open (open/in_progress) plays."""
    from api.dashboards_service import action_plan

    assert tenant.id is not None
    tenant_id = tenant.id
    try:
        with session.begin_nested():
            plan_d: dict = action_plan(session, tenant_id)
    except Exception:  # noqa: BLE001 — degrade to the plays that don't need it
        log.exception("recommendations: action plan failed")
        plan_d = {}

    frozen: set[str] = set()
    if not plan_d:
        frozen |= _SOURCE_BRANCHES["refresh"] | _SOURCE_BRANCHES["sources"]
    sources: list[tuple[str, Callable[[], list[Play]]]] = [
        ("query", lambda: _query_plays(session, tenant_id, plan_d)),
        ("accuracy", lambda: _accuracy_plays(session, tenant_id)),
        ("agents", lambda: _agent_plays(session, tenant_id)),
        ("refresh", lambda: _refresh_plays(plan_d)),
        ("subquery", lambda: _subquery_plays(session, tenant_id)),
        ("sources", lambda: _source_plays(plan_d)),
        ("owned_docs", lambda: _owned_docs_play(session, tenant_id, plan_d)),
        ("strategy", lambda: _strategy_play(session, tenant_id)),
    ]
    plays: list[Play] = []
    for name, fn in sources:
        plays += _run_source(session, name, fn, frozen)

    # A lost citation stays a to-do until the page is cited again, not just
    # until it drops out of the latest two-run comparison.
    protect = plan_d.get("protect") or {}
    still_lost: set[str] = set()
    if "latest_cited" in protect:
        cited_now = set(protect["latest_cited"])
        still_lost = {
            r.gap_ref for r in session.exec(
                select(Recommendation).where(
                    Recommendation.tenant_id == tenant_id,
                    Recommendation.branch == "refresh",
                    col(Recommendation.status).in_(
                        [RecommendationStatus.open, RecommendationStatus.in_progress]),
                )
            ).all()
            if r.gap_ref.removeprefix("refresh:") not in cited_now
        }

    existing = {
        r.gap_ref: r
        for r in session.exec(
            select(Recommendation).where(Recommendation.tenant_id == tenant_id)
            .order_by(col(Recommendation.id))
        ).all()
    }
    open_count = 0
    seen: set[str] = set()
    for p in plays:
        if p.gap_ref in seen:
            continue
        seen.add(p.gap_ref)
        rec = existing.pop(p.gap_ref, None)
        if rec is None:
            rec = Recommendation(tenant_id=tenant_id, gap_ref=p.gap_ref, branch=p.branch,
                                 action_text=p.action_text)
        elif rec.status == RecommendationStatus.resolved:
            rec.status = RecommendationStatus.open  # the gap came back
        # Text and ranking follow the latest data; the human's status is kept.
        rec.branch, rec.title, rec.action_text = p.branch, p.title, p.action_text
        rec.priority, rec.evidence, rec.why = p.priority, p.evidence, p.why
        rec.steps, rec.query_text, rec.link = list(p.steps), p.query_text, p.link
        rec.updated_at = utcnow()
        session.add(rec)
        if rec.status in (RecommendationStatus.open, RecommendationStatus.in_progress):
            open_count += 1

    # Anything left no longer matches a live gap: auto-resolve unless a human
    # already closed it, its source couldn't judge this time, or it's a lost
    # citation that hasn't been won back.
    for rec in existing.values():
        if rec.status in HAND_STATUSES or rec.status == RecommendationStatus.resolved:
            continue
        if rec.branch in frozen or rec.gap_ref in still_lost:
            open_count += 1
            continue
        rec.status = RecommendationStatus.resolved
        rec.updated_at = utcnow()
        session.add(rec)
    session.commit()
    return open_count
