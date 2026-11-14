"""The recommendations playbook: one to-do list built from every signal
EverPresent measures, each play specific to the tenant's own data, sorted
into the area of work it belongs to, and ranked by projected impact.

Areas (api.impact.CATEGORIES), each a different kind of work:
  structure    can AI reach and read the site: blocked bots, noindex, pages
               that error, pages Brave doesn't hold
  content      do the brand's pages answer what buyers ask: one play per
               question (search and Google's AI answer together), the
               sub-searches behind it, lost citations, pages read but never
               cited, primary evidence
  accuracy     is what AI says right: wrong facts in answers, own pages that
               contradict the fact sheet
  third_party  the lists, articles and reference entries AI cites, one play
               per site, with the pages named and what is realistic for each
  reviews      review platforms cited for the brand's questions
  community    threads and videos AI quotes
  platforms    store listings and engine platforms (Meta)
  setup        what would let us measure more; not ranked

Ranking (api.impact): reach x gap x odds. Reach and gap are counted from the
last 28 days of answers, weighted by engine audience like the headline; odds
come from who controls the fix and how strong the evidence is. Each play
also says how big the job is and when answers can show the result.

Regeneration is idempotent: gap_ref is stable, a human's status is kept, the
text and rank refresh to the latest data, closed gaps auto-resolve, and
reopened gaps come back."""

import logging
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlmodel import Session, col, select

from api.impact import (
    Reach,
    Universe,
    assign_bands,
    engines_phrase,
    impact,
    priority_of,
)
from api.models import (
    AccuracyFinding,
    Citation,
    FanoutShard,
    Mention,
    PagePresence,
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
from api.source_routes import is_list_page, source_kind

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
    category: str = ""   # api.impact.CATEGORIES
    control: str = ""    # own | influence | earn
    effort: str = ""     # hours | days | weeks
    speed: str = ""      # days | weeks | months | model
    impact: dict = field(default_factory=dict)
    targets: list[dict] = field(default_factory=list)


def _rank(
    p: Play,
    uni: Universe | None,
    ids: Iterable[int] | None = None,
    *,
    reach: Reach | None = None,
    directness: float = 1.0,
    severity: float = 1.0,
    risk: float = 0.0,
    floor: float = 0.0,
    basis: str = "",
    at_stake: bool = False,
) -> Play:
    """Score a play on the one scale (api.impact) and set its sort key."""
    if reach is None and uni is not None and ids is not None:
        reach = uni.reach(ids)
    p.impact = impact(reach, control=p.control, evidence=p.evidence, directness=directness,
                      severity=severity, risk=risk, floor=floor, basis=basis, universe=uni,
                      at_stake=at_stake)
    p.priority = priority_of(p.impact["score"])
    return p


def _short_path(url: str, n: int = 48) -> str:
    """A URL as a reader would say it: host and path, no scheme or query."""
    parts = urlsplit(url or "")
    text = (parts.hostname or "").removeprefix("www.") + (parts.path.rstrip("/") or "")
    text = text or url
    return text if len(text) <= n else text[: n - 1] + "…"


def _path_of(url: str) -> str:
    return urlsplit(url or "").path.rstrip("/") or "/"


def _citations(session: Session, uni: Universe) -> list[tuple[int, str, str, str]]:
    """(answer id, domain, url, source category) for every citation on the
    universe's answers. Read once per universe and kept on it."""
    cached = getattr(uni, "_cites", None)
    if cached is None:
        cached = [
            (rid, (domain or "").lower().removeprefix("www."), url or "", cat or "")
            for rid, domain, url, cat in session.exec(
                select(col(Citation.result_id), col(Citation.domain), col(Citation.url),
                       col(Citation.source_category))
                .join(Result, col(Result.id) == col(Citation.result_id))
                .where(*uni.conds)
            ).all()
        ]
        uni._cites = cached  # type: ignore[attr-defined]
    return cached


def _own_page_answers(session: Session, uni: Universe) -> dict[str, set[int]]:
    """Answers that cite each of the brand's own pages, by path."""
    cached = getattr(uni, "_own_pages", None)
    if cached is None:
        cached = defaultdict(set)
        for rid, _domain, url, cat in _citations(session, uni):
            if cat == "brand":
                cached[_path_of(url)].add(rid)
        uni._own_pages = cached  # type: ignore[attr-defined]
    return cached


# Evidence statements, one per kind of play, so every play of a kind cites the
# same dated finding. Policy: name the source (see research_notes/ and
# DECISIONS.md) and the kind of evidence, but don't quote a figure that hasn't
# been checked against its original source (most 2026 industry numbers
# circulate second-hand). Official guidance is cited as such.
WHY = {
    "subquery": (
        "Engines answer by running several sub-searches and citing pages that answer "
        "those, often pages that don't rank for the main question (Ahrefs, BrightEdge and "
        "Surfer SEO data on Google's AI Overviews, 2025–2026; correlational)."
    ),
    "facts": (
        "In a May 2026 controlled study across several models, topical relevance, explicit "
        "prices and recent dates raised citation odds; formatting alone did not (arXiv "
        "preprint 2605.25517)."
    ),
    "earned": (
        "For comparison questions, AI answers cite third-party sources (reviews, "
        "publishers, lists) far more often than brands' own pages (July 2026 survey of "
        "GEO research, arXiv 2607.14035)."
    ),
    "reviews": (
        "In a June 2026 controlled test, a small rating advantage was enough to change which "
        "brand an AI recommended (arXiv 2606.17443). Brands with active review profiles are "
        "cited more often (Seer Interactive study sponsored by Trustpilot; correlational)."
    ),
    "community": (
        "Google's AI answers and Perplexity often cite Reddit, YouTube and forums. ChatGPT "
        "cut its citations of them sharply in August 2026 (Otterly and Qwairy tracking; "
        "correlational). Astroturfing gets removed and can backfire."
    ),
    "reference": (
        "Wikipedia is among the most-cited sites in ChatGPT answers (Profound citation "
        "data), and reference entries feed both live answers and future model training."
    ),
    "accuracy": (
        "When an answer that searched the web gets a fact wrong, it is usually repeating a "
        "wrong or out-of-date page it cited. Fix that page, request a recrawl and re-check "
        "over several runs."
    ),
    "crawler": (
        "Official: ChatGPT search only shows sites OAI-SearchBot can crawl; Copilot uses "
        "Bing's index; Google's AI features need normal Googlebot indexing; Claude's search "
        "runs on Brave, whose crawler follows Googlebot's rules. If the bot is blocked, that "
        "engine can't show your pages."
    ),
    "refresh": (
        "AI answers tend to cite recently updated pages (Ahrefs citation study, 2025). A "
        "lost citation is the first sign a page is slipping, and a refresh costs little."
    ),
    "broken": (
        "A page that errors for bots can't be quoted; a cited URL that 404s stays lost "
        "until it's fixed or redirected."
    ),
    "read_not_cited": (
        "AI search bots already fetch these pages but cite other sources. The engines find "
        "them, so the fix is on the page itself, which makes this a cheap gap to close."
    ),
    "training": (
        "Answers from memory change only when a new model is trained. Brands with strong "
        "coverage on other sites are named more often, and nothing here moves fast."
    ),
    "aio": (
        "Official: Google says AI Overviews and AI Mode need no special markup, only "
        "indexable, snippet-eligible pages. They often cite pages that answer the "
        "sub-searches as well as top-ranked ones."
    ),
    "logs": (
        "Only server logs show whether ChatGPT, Perplexity, Claude and Google's AI bots "
        "can actually reach your pages, and which pages they read."
    ),
    "site_search": (
        "Some of ChatGPT's sub-searches are limited to a single site, and for the most-searched "
        "domains most of those went to brand sites (Ahrefs' October 2026 study of ChatGPT "
        "answers). What that site says is likely to be what the answer says."
    ),
    "meta": (
        "Meta AI answers with Meta's Muse Spark model. Besides the web, the app can search "
        "Facebook, Instagram and Threads posts and product catalogs (Simon Willison's "
        "review of meta.ai's tools, April 2026), and Meta's crawler documentation lists "
        "meta-webindexer for Meta AI search. Little is published yet on what makes it "
        "name one brand over another."
    ),
    "muse": (
        "Muse, Meta's shopping agent (US since Sept 8, 2026, Singapore since Oct 28; not "
        "in Canada as of Oct 31, 2026), browses stores itself. "
        "In Profound's test (Oct 2026, 50 prompts, one category) about 4 of its 6 picks "
        "came from the open web rather than Meta's catalog. Its reported instructions "
        "rank well-known merchants first, check at most three web stores per request, "
        "and put a named brand's own store first; in-chat checkout covers only catalog "
        "products flagged for agentic checkout. A small sample and a reported file, so "
        "directional."
    ),
    "research": (
        "ChatGPT has shifted toward citing the original source of a fact, such as studies "
        "and official data, over sites that summarize it (Ahrefs' October 2026 study of "
        "ChatGPT answers). Reformatting a page mostly shifts credit between sources rather "
        "than adding citations (CITECHOICE preprint, arXiv 2609.15164)."
    ),
    "own_pages": (
        "Newer ChatGPT models do much of their searching on the brand's own site (Peec AI "
        "and Writesonic tracking, 2026), so what your pricing and help pages say is likely "
        "what the answer says."
    ),
    "model_change": (
        "A new model can change how often an engine searches and what it cites overnight. "
        "Compare periods on the same model rather than across the switch."
    ),
    "strategy": (
        "A May 2026 audit found many specialist brands never appear in answers and "
        "mid-market brands are named far more often than they're recommended (arXiv "
        "2605.27439, vendor-affiliated). A June 2026 preprint found engines answering from "
        "memory invent more sources for well-known brands (arXiv 2606.21595). The right "
        "play depends on where you start."
    ),
}

# The sub-search plays pair the retrieval mechanism (correlational) with the
# controlled result on what gets cited once a page is retrieved.
WHY_SUBQUERY_FACTS = f"{WHY['subquery']} {WHY['facts']}"

_RECRAWL = (
    "Request a recrawl after the change: IndexNow (Bing, which feeds Copilot and, by most "
    "accounts, ChatGPT search), URL Inspection in Google Search Console, and Brave's "
    "submit-a-URL form (Claude's search runs on Brave); ChatGPT and Perplexity have no "
    "recrawl request"
)


def _join(items: list[str], n: int = 3) -> str:
    items = [i for i in items if i][:n]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


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
_GOOGLE_AI = ("google_aio", "google_ai_mode")

# How squarely a page fix acts, by how settled the answer is (Action Plan's
# contestability): an answer whose named brands keep changing is still being
# decided; one that names the same brands every run is harder to enter.
_CONTEST_DIRECTNESS = {"winnable now": 1.0, "contested": 0.85, "needs history": 0.85,
                       "locked in": 0.5}


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


def _query_plays(
    session: Session, tenant_id: int, plan: dict, uni: Universe | None = None
) -> list[Play]:
    """One page-level play per question the brand is missing from. A search
    gap and a Google AI Overview gap on the same question are one job (the
    same page), so they are one play; the sub-searches behind the question
    are its checklist. Questions engines answer from memory can't be won
    with a page, so they are gathered into one long-term play."""
    from api.dashboards_service import _surface_label

    uni = uni or Universe(session, tenant_id)
    briefs = {b["query"]: b for b in plan.get("briefs", [])}
    context = _query_context(session, tenant_id)
    by_query: dict[str, dict[str, dict[str, list[str]]]] = {}
    for (query_text, branch), presence in _query_gaps(session, tenant_id).items():
        by_query.setdefault(query_text, {})[branch] = presence

    plays: list[Play] = []
    memory: list[str] = []
    for query_text in sorted(by_query):
        branches = by_query[query_text]
        if "training" in branches:
            memory.append(query_text)
        search_gap, aio_gap = "web_search" in branches, "aio" in branches
        if not (search_gap or aio_gap):
            continue
        branch = "web_search" if search_gap else "aio"
        presence = branches[branch]
        missing = [_surface_label(x) for x in presence["missing"]]
        named_on = [_surface_label(x) for x in presence["named"]]
        b = briefs.get(query_text) or {}
        c = context.get(query_text) or {}
        rivals = b.get("competitors_winning") or c.get("rivals") or []
        # Only sub-searches the engines actually ran; the brief's fallback of
        # related questions is not what "engines search" means.
        subs = c.get("subs") or (
            b.get("subtopics") if b.get("subtopics_source") == "observed" else []) or []
        cit = b.get("citability") or {}
        your_page = ((cit.get("your_page") or {}).get("url") or "") if cit.get("ready") else ""
        page_gaps = [g for g in (cit.get("gaps") or [])
                     if your_page and not g.startswith("Your page has what")]
        winners = list(cit.get("winners") or []) if cit.get("ready") else []
        contest = (b.get("contestability") or {}).get("label", "needs history")

        if search_gap:
            text = f'AI answers for "{query_text}" search the web and mostly leave you out'
            text += f"; {_join(rivals)} show up instead." if rivals else "."
            if named_on:
                text += (f" You're named on {_join(named_on, 4)} but missing on "
                         f"{_join(missing, 4)}.")
            if aio_gap:
                text += " Google's AI Overview answers it without citing you."
        else:
            text = f'Google\'s AI Overview answers "{query_text}" without citing you'
            text += f"; it names {_join(rivals)}." if rivals else "."
        title = (f"Upgrade {_short_path(your_page, 36)} to win “{query_text}”" if your_page
                 else f"Build the page that answers “{query_text}”")

        steps: list[str] = []
        if not your_page:
            steps.append("Check whether a page of yours already covers this question; if one "
                         "does, upgrade it rather than writing a second")
        if subs:
            steps.append("Answer the sub-questions engines search, each under its own "
                         f"heading: {_join(subs, 4)}")
        steps.extend(page_gaps[:2])
        if not page_gaps:
            steps.append("State prices, plans, limits and dates as plain text on that page")
        if aio_gap:
            steps.append("For Google's AI answer, check the page is indexed and "
                         "snippet-eligible (no nosnippet; content in the HTML, not only in "
                         "scripts). Skip special AI markup: Google says none is needed")
        if b.get("spam_risk"):
            steps.append("Don't answer it with your own ranked 'best X' list (see Don'ts)")
        steps.append("Log the change in Outcome with an untouched control page, then "
                     "judge it after 2–3 weeks of runs")

        targets: list[dict] = []
        if your_page:
            targets.append({"kind": "Your page", "label": _short_path(your_page),
                            "url": your_page, "note": "already cited for this question"})
        targets += [{"kind": "Sub-question", "label": s, "note": "you're absent from its results"}
                    for s in subs[:5]]
        targets += [{"kind": "Cited instead", "label": _short_path(w), "url": w}
                    for w in winners[:3]]

        link = (f"/dashboard/action-plan#brief-{b['query_id']}" if b.get("query_id")
                else "/dashboard/action-plan")
        p = Play(
            f"query:{query_text}::branch:{branch}", branch, title, text, 0,
            "strong" if search_gap else "official",
            WHY_SUBQUERY_FACTS if search_gap else WHY["aio"],
            steps, query_text, link, category="content", control="own", effort="days",
            speed="weeks", targets=targets)
        directness = _CONTEST_DIRECTNESS.get(contest, 0.85)
        if search_gap:
            _rank(p, uni, uni.for_query(query_text), directness=directness)
        else:
            # Only Google's AI answer is missing: its answers to this question
            # are the reach. Where the Overview was read off the results page
            # and not measured as an answer, fall back to its audience share
            # spread over the questions.
            ids = uni.for_query(query_text, _GOOGLE_AI)
            floor = (100 * sum(uni.family_share.get(f, 0.0) for f in _GOOGLE_AI)
                     / max(1, uni.questions) * 0.6 * 0.6)
            _rank(p, uni, ids, directness=0.6, floor=round(floor, 2),
                  basis="" if ids else "Google shows an AI Overview for this question and "
                                       "cites none of your pages.")
        plays.append(p)

    if memory:
        listed = [f"“{q}”" for q in memory]
        more = f" and {len(memory) - 3} more" if len(memory) > 3 else ""
        ids = [i for q in memory for i in uni.for_query(q)]
        n = len(memory)
        p = Play(
            "training:memory", "training",
            f"Build coverage for {n} question{'s' if n != 1 else ''} engines answer from "
            "memory",
            f"Engines answer {', '.join(listed[:3])}{more} from memory, without searching, "
            "and mostly leave you out. A new page won't change these answers.",
            0, "emerging", WHY["training"],
            ["Earn coverage in the sources models learn from: independent reviews, trade "
             "press and reference entries (Third-party mentions lists the ones cited today)",
             "Make sure your own pages say what you do in plain, quotable sentences",
             "Expect movement only when a new model version ships"],
            link="/dashboard/action-plan", category="third_party", control="earn",
            effort="weeks", speed="model",
            targets=[{"kind": "Question", "label": q} for q in memory[:8]])
        plays.append(_rank(p, uni, ids, directness=0.5))
    return plays


def _accuracy_plays(
    session: Session, tenant_id: int, uni_all: Universe | None = None
) -> list[Play]:
    """One play per wrong fact. Ranked on the answers about the brand: a
    wrong price reaches the buyers closest to choosing."""
    from api.dashboards_service import (
        _latest_results_by_variant,
        _owned_domains,
        _surface_label,
    )
    from engine.processing.citations import domain_is_owned

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
    if not groups:
        return []
    uni_all = uni_all or Universe(session, tenant_id, scope="all")
    about_you = Universe(session, tenant_id, scope="branded")
    # Every answer in the window that stated each fact wrong, not only the
    # latest ones: how often it is said is the size of the problem.
    wrong: dict[int, set[int]] = defaultdict(set)
    for fact_id, rid in session.exec(
        select(col(AccuracyFinding.fact_id), col(AccuracyFinding.result_id))
        .join(Result, col(Result.id) == col(AccuracyFinding.result_id))
        .where(*uni_all.conds, col(AccuracyFinding.fact_id).in_(list(groups)))
    ).all():
        wrong[fact_id].add(rid)
    owned = _owned_domains(session, tenant_id)
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
        on_own_site = any(domain_is_owned(urlsplit(u).hostname or "", owned) for u in top)
        steps = []
        if top:
            steps.append(f"Check the pages those answers cite, and get them corrected: "
                         f"{_join(top, 4)}")
        steps += [f"State the correct {f.subject} ({f.expected}) plainly on your own page, "
                  "with an updated date", _RECRAWL,
                  "Re-check over the next 2–3 runs; answers from memory may not change "
                  "until the next model version"]
        p = Play(
            f"accuracy:{fact_id}", "accuracy",
            f"Fix a wrong fact: {f.subject}",
            f"{_join(engines, 4)} say {f.subject} is {stated}; it's {f.expected}.",
            0, "moderate", WHY["accuracy"], steps, link="/dashboard/brand",
            category="accuracy", control="own" if on_own_site or not top else "influence",
            effort="hours", speed="weeks",
            targets=[{"kind": "Source cited", "label": _short_path(u), "url": u,
                      "detail": f"{urls[u]}×"} for u in top])
        ids = wrong.get(fact_id) or set(rids)
        base = about_you if any(i in about_you.answers for i in ids) else uni_all
        reach = base.reach(ids, problem=lambda _a: True)
        whose = "answers about you" if base is about_you else "measured answers"
        basis = (f"Stated wrong in {reach.answers} of the {len(base):,} {whose} in the last "
                 f"28 days ({engines_phrase(reach.families)}).") if reach.answers else ""
        plays.append(_rank(p, base, reach=reach, severity=1.5, floor=0.6, basis=basis,
                           at_stake=True))
    return plays


# The bots that decide whether an engine can show the site at all, the
# engines each one gates, and the engine families that reach is counted on.
_KEY_BOTS = {
    "OAI-SearchBot": "ChatGPT search",
    "Bingbot": "Copilot (official) and, by most accounts, ChatGPT search",
    "PerplexityBot": "Perplexity",
    "Claude-SearchBot": "Claude",
    "Googlebot": "Google AI Overviews and AI Mode, and Claude (its search runs on Brave, "
                 "whose crawler follows Googlebot's rules)",
}
_BOT_FAMILIES = {
    "OAI-SearchBot": ("chatgpt",),
    "Bingbot": ("copilot",),  # the documented dependency only
    "PerplexityBot": ("perplexity",),
    "Claude-SearchBot": ("claude",),
    "Googlebot": ("google_aio", "google_ai_mode", "gemini", "claude"),
}
_MIN_LOG_HITS = 200  # below this, a missing bot is more likely a partial log
# Letting a crawler in makes pages eligible to be cited; it doesn't write the
# answer. Half of the gap on that engine is the most it is credited with.
_CRAWLER_DIRECTNESS = 0.5


def _agent_plays(
    session: Session, tenant_id: int, uni: Universe | None = None,
    uni_all: Universe | None = None,
) -> list[Play]:
    from api.agent_analytics import agent_analytics

    a = agent_analytics(session, tenant_id)
    if not a.get("has_data") and a.get("stale"):
        # Logs were uploaded once but none are recent: ask for fresh logs and
        # leave the existing bot plays as they are (no data isn't "fixed").
        raise _KeepExisting([Play(
            "connect_logs", "connect_logs", "Upload recent server logs",
            f"Your newest AI-bot log data is more than {a['days']} days old, so bot "
            "access and page checks are on hold.",
            _SETUP_PRIORITY, "moderate", WHY["logs"],
            ["Upload the last 30 days of access logs on the AI Agents tab, or set up "
             "the automatic push from your CDN so the data stays current"],
            link="/dashboard/agents", category="setup", control="own", effort="hours")])
    if not a.get("has_data"):
        return [Play(
            "connect_logs", "connect_logs", "Connect your server logs",
            "See which AI bots can reach your site and which pages they read.",
            _SETUP_PRIORITY, "moderate", WHY["logs"],
            ["Upload a recent access log on the AI Agents tab, or set up the automatic "
             "push from your CDN"], link="/dashboard/agents", category="setup",
            control="own", effort="hours")]
    uni = uni or Universe(session, tenant_id)
    plays: list[Play] = []
    bots = {b["bot"]: b for b in a["by_bot"]}
    if a["total_hits"] >= _MIN_LOG_HITS:
        for bot, engine in _KEY_BOTS.items():
            b = bots.get(bot)
            ids = uni.for_families(_BOT_FAMILIES[bot])
            if b is None:
                p = Play(
                    f"crawler:{bot}:absent", "crawler_access",
                    f"{bot} hasn't visited in {a['days']} days",
                    f"Without {bot}, {engine} can't show your pages.",
                    0, "official", WHY["crawler"],
                    [f"Check robots.txt allows {bot} (you can still block training-only "
                     "bots like GPTBot)",
                     "Check CDN and firewall rules: Cloudflare's September 2026 defaults "
                     f"allow search crawlers, so a missing {bot} usually means a custom "
                     "WAF rule or a pre-July 'block all AI' toggle",
                     "Confirm the site is indexed in Bing Webmaster Tools and Google "
                     "Search Console"],
                    link="/dashboard/agents", category="structure", control="own",
                    effort="hours", speed="days")
                plays.append(_rank(p, uni, ids, directness=_CRAWLER_DIRECTNESS, floor=1.0))
            elif b["hits"] and b.get("blocked", 0) / b["hits"] > 0.2 and b["blocked"] >= 20:
                # Only refusals count (401/403/429/5xx): a 404 is a dead page,
                # handled by the broken-pages play, not the bot being blocked.
                share = b["blocked"] / b["hits"]
                pct = round(100 * share)
                p = Play(
                    f"crawler:{bot}:errors", "crawler_access",
                    f"{bot} is refused on {pct}% of requests",
                    f"{engine} is being turned away from much of your site.",
                    0, "official", WHY["crawler"],
                    ["Check firewall, bot-challenge and rate-limit rules for "
                     f"{bot} (403, 429 and 5xx responses)",
                     "Find the affected pages on the AI Agents tab (Most-read pages)"],
                    link="/dashboard/agents", category="structure", control="own",
                    effort="hours", speed="days")
                plays.append(_rank(p, uni, ids, directness=_CRAWLER_DIRECTNESS * share,
                                   floor=0.8))
    cited_by = _own_page_answers(session, uni_all) if uni_all is not None else {}
    for at_risk in a.get("cited_at_risk", [])[:5]:
        if "error" in at_risk["reason"]:
            path = at_risk["path"]
            p = Play(
                f"at_risk:{path}", "broken_page",
                f"A cited page is erroring for AI bots: {path}",
                f"AI answers cite {path} ({at_risk['cited']}×), but it returned "
                f"{at_risk['reason']}.",
                0, "moderate", WHY["broken"],
                ["Fix the error or 301 it to the live page", _RECRAWL],
                link="/dashboard/agents", category="structure", control="own",
                effort="hours", speed="days")
            reach = (uni_all.reach(cited_by.get(path, ()), problem=lambda _a: True)
                     if uni_all is not None else None)
            basis = (f"{reach.answers} answers in the last 28 days cite this page; they lose "
                     "it if it keeps erroring.") if reach and reach.answers else ""
            plays.append(_rank(p, uni_all, reach=reach, floor=0.6, basis=basis, at_stake=True))
    broken = a.get("broken_pages", [])[:8]
    if broken:
        total = sum(pg["errors"] for pg in broken)
        paths = [pg["path"] for pg in broken]
        p = Play(
            "broken_pages", "broken_page",
            f"Redirect {len(broken)} dead page{'s' if len(broken) != 1 else ''} AI bots "
            "keep requesting",
            f"AI bots got {total:,} errors on {_join(paths, 5)}"
            + (f" and {len(paths) - 5} more" if len(paths) > 5 else "") + ".",
            0, "moderate", WHY["broken"],
            ["301 each to the closest live page", "Remove them from sitemaps and internal "
             "links", _RECRAWL], link="/dashboard/agents", category="structure",
            control="own", effort="hours", speed="days",
            targets=[{"kind": "Dead page", "label": pg["path"],
                      "detail": f"{pg['errors']:,} errors"} for pg in broken])
        plays.append(_rank(p, None, floor=0.3,
                           basis=f"AI bots hit {total:,} errors on these pages in "
                                 f"{a['days']} days. No measured answer depends on them yet."))
    rnc = a.get("read_not_cited", [])[:8]
    if rnc:
        reads = sum(pg["search"] + pg["user"] for pg in rnc)
        paths = [f"{pg['path']} ({pg['search'] + pg['user']:,} reads)" for pg in rnc]
        p = Play(
            "read_not_cited", "read_not_cited",
            f"{len(rnc)} page{'s' if len(rnc) != 1 else ''} AI reads but never cites",
            f"AI search keeps fetching {_join(paths, 5)}, but no measured answer cites "
            f"{'it' if len(rnc) == 1 else 'them'}.",
            0, "moderate", WHY["read_not_cited"],
            ["Check the content is in the HTML (view it with JavaScript off)",
             "Lead with a direct answer; state prices, dates and specs as text",
             "Make sure each answers the sub-questions engines search for its topic"],
            link="/dashboard/agents", category="content", control="own", effort="days",
            speed="weeks",
            targets=[{"kind": "Read, not cited", "label": pg["path"],
                      "detail": f"{pg['search'] + pg['user']:,} reads"} for pg in rnc])
        plays.append(_rank(p, None, floor=0.6,
                           basis=f"AI search fetched these pages {reads:,} times in "
                                 f"{a['days']} days and cited none of them."))
    return plays


def _refresh_plays(
    plan: dict, uni: Universe | None = None, session: Session | None = None
) -> list[Play]:
    """A brand page that dropped out of the latest run's citations. What is
    at stake is the answers that were citing it, so that is its reach: a page
    cited everywhere outranks one that was cited once."""
    plays = []
    cited_by = (_own_page_answers(session, uni)
                if uni is not None and session is not None else {})
    for lost in (plan.get("protect") or {}).get("lost", [])[:6]:
        url, queries = lost["url"], lost["queries"]
        p = Play(
            f"refresh:{url}", "refresh", f"Win back a lost citation: {_short_path(url)}",
            f"This page stopped being cited for {_join([f'“{q}”' for q in queries], 3)}.",
            0, "moderate", WHY["refresh"],
            ["Update the numbers, examples and dates; show 'Updated <month year>'",
             "Check it still answers those questions directly, near the top",
             "Check it loads for bots (AI Agents tab)", _RECRAWL],
            link="/dashboard/action-plan", category="content", control="own",
            effort="hours", speed="weeks",
            targets=[{"kind": "Your page", "label": _short_path(url), "url": url},
                     *({"kind": "Lost on", "label": q} for q in queries[:5])])
        reach, basis = None, ""
        if uni is not None:
            asked = set(queries)
            reach = uni.reach(
                [i for i in cited_by.get(_path_of(url), ()) if uni.answers[i].query_text in asked],
                problem=lambda _a: True)
            if reach.answers:
                basis = (f"{reach.answers} answers in the last 28 days cited this page for "
                         f"{'this question' if len(asked) == 1 else 'these questions'} "
                         f"({engines_phrase(reach.families)}); the latest run cites it for "
                         "none of them.")
        plays.append(_rank(p, uni, reach=reach, directness=0.8, floor=0.5, basis=basis,
                           at_stake=True))
    return plays


def _subquery_plays(
    session: Session, tenant_id: int, uni: Universe | None = None,
    covered: frozenset[str] = frozenset(),
) -> list[Play]:
    """Sub-searches where the brand is absent, per parent question. Questions
    that already have a page play carry their sub-questions there, so only
    the rest (named in the answer, absent from the searches behind it) get a
    play of their own."""
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
        if sh.parent_query_text not in covered:
            by_parent.setdefault(sh.parent_query_text, []).append(sh)
    if not by_parent:
        return []
    uni = uni or Universe(session, tenant_id)
    plays = []
    for parent, group in by_parent.items():
        group.sort(key=lambda x: (-x.reach, x.shard_norm))
        winners = sorted({w for sh in group for w in (sh.winners or [])})
        listed = [f"“{sh.shard_text}”" for sh in group[:5]]
        p = Play(
            f"subquery:{parent}", "subquery",
            f"Cover the sub-questions behind “{parent}”",
            f"To answer “{parent}”, engines also search {_join(listed, 5)}"
            + (f" (and {len(group) - 5} more)" if len(group) > 5 else "")
            + ". You're absent from those results"
            + (f"; {_join(winners)} {'appears' if len(winners) == 1 else 'appear'}."
               if winners else "."),
            0, "strong", WHY_SUBQUERY_FACTS,
            ["Answer each sub-question in its own section (or page), first lines under "
             "a clear heading",
             "State the facts they ask about explicitly: numbers, prices, dates",
             "Check which pages rank for them and whether you can be listed there"],
            query_text=parent, link="/dashboard/fanout", category="content", control="own",
            effort="days", speed="weeks",
            targets=[{"kind": "Sub-question", "label": sh.shard_text,
                      "note": (f"{_join(list(sh.winners), 2)} "
                               f"{'appears' if len(sh.winners) == 1 else 'appear'}"
                               if sh.winners else "you're absent")}
                     for sh in group[:6]])
        # The sub-searches decide which pages the answer is written from, so
        # a quarter of the question's answers count as at stake even where
        # the brand is named today; rivals on those results make it likelier.
        plays.append(_rank(p, uni, uni.for_query(parent), directness=0.7,
                           risk=0.35 if winners else 0.2, floor=0.3))
    plays.sort(key=lambda p: (-p.impact["score"], p.gap_ref))
    return plays[:6]


# --------------------------------------------------- third-party sources ----
#
# "Get listed on these sites" is not a recommendation. A source earns a play
# only when it keeps being cited for the brand's questions while naming
# rivals, and each play names the pages, says whether the brand is on them,
# and says what route in is realistic for that kind of page. Routes that
# don't exist are said so: a published news article is not edited to add a
# brand, and nobody gets into someone else's video.

MIN_SOURCE_ANSWERS = 3   # cited in fewer answers than this is noise
MIN_SOURCE_RUNS = 2      # ...and in one run only is a one-off (when 2+ runs exist)
MAX_SOURCE_PLAYS = 8
MAX_PER_SOURCE_KIND = 3

def _source_stats(session: Session, tenant_id: int, uni: Universe) -> list[dict]:
    """Third-party sites cited on the measured answers that are worth a play:
    cited repeatedly, across runs, and alongside rivals at least twice as
    often as alongside the brand."""
    from api.dashboards_service import _owned_domains
    from engine.processing.citations import domain_is_owned

    owned = _owned_domains(session, tenant_id)
    rivals_on: dict[int, set[str]] = defaultdict(set)
    for rid, name in session.exec(
        select(col(Mention.result_id), col(Mention.entity_name))
        .join(Result, col(Result.id) == col(Mention.result_id))
        .where(*uni.conds, Mention.entity_type != "brand")
    ).all():
        rivals_on[rid].add(name)
    sites: dict[str, dict] = {}
    for rid, domain, url, cat in _citations(session, uni):
        # Rivals' own sites are "competitor": nothing to earn there.
        if cat != "other" or not domain or domain_is_owned(domain, owned):
            continue
        if rid not in uni.answers:
            continue
        s = sites.setdefault(domain, {"answers": set(), "pages": defaultdict(set)})
        s["answers"].add(rid)
        s["pages"][url].add(rid)
    out = []
    for domain, s in sites.items():
        ids: set[int] = s["answers"]
        rival_n = sum(1 for i in ids if rivals_on.get(i))
        brand_n = sum(1 for i in ids if uni.answers[i].named)
        if len(ids) < MIN_SOURCE_ANSWERS or rival_n < 2 or brand_n * 2 > rival_n:
            continue
        reach = uni.reach(ids)
        if uni.runs >= MIN_SOURCE_RUNS and reach.runs < MIN_SOURCE_RUNS:
            continue
        kind = source_kind(domain)
        if kind == "research":
            continue  # primary sources are cited, not pitched: see _research_play
        rivals = [n for n, _c in Counter(
            n for i in ids for n in rivals_on.get(i, ())).most_common(3)]
        pages = sorted(s["pages"].items(), key=lambda kv: (-len(kv[1]), kv[0]))[:4]
        out.append({"domain": domain, "kind": kind, "ids": ids, "reach": reach,
                    "rivals": rivals, "brand_n": brand_n,
                    "pages": [(url, len(rids)) for url, rids in pages]})
    return out


def _source_play(s: dict, uni: Universe, crawled: dict[str, PagePresence]) -> Play:
    domain, kind, reach = s["domain"], s["kind"], s["reach"]
    pages: list[tuple[str, int]] = s["pages"]
    q = reach.questions
    lists = [u for u, _n in pages if is_list_page(u)]
    if kind == "publisher":
        kind = "list" if lists else "article"
    top = crawled.get(pages[0][0]) if pages else None
    on_page: bool | None = top.brand_found if top is not None else None

    text = f"AI cites {domain} for {q} of your question{'s' if q != 1 else ''}"
    text += (f", in {reach.runs} of your last {uni.runs} runs."
             if uni.runs >= MIN_SOURCE_RUNS else ".")
    if s["rivals"]:
        text += f" Those answers name {_join(s['rivals'])}."
    if on_page is False:
        text += " The page cited most doesn't mention you."
    elif on_page:
        text += (" The page cited most already mentions you, so the gap is how it describes "
                 "you, not whether you're there.")

    targets = []
    for url, cited in pages:
        row = crawled.get(url)
        note = ""
        if row is not None:
            named = _join(list(row.competitors_found or []), 3)
            note = ("mentions you" if row.brand_found else "doesn't mention you") + (
                f"; names {named}" if named else "")
        targets.append({"kind": "List" if url in lists else "Cited page",
                        "label": _short_path(url), "url": url,
                        "detail": f"cited in {cited} answer{'s' if cited != 1 else ''}",
                        "note": note})

    already = ("You're already on the page cited most: check how it describes you (position, "
               "rating, facts) and get anything out of date corrected")
    directness = 1.0
    if kind == "review":
        branch, category, control, effort, speed, evidence = (
            "reviews", "reviews", "influence", "weeks", "months", "moderate")
        why = WHY["reviews"]
        title = f"Close the review gap on {domain}"
        steps = [
            "Claim your profile and complete it: plans, prices, categories and screenshots "
            "that match your site",
            "Get listed in the category pages these answers cite, not only on your own "
            "profile",
            "Ask recent customers for a review after a good experience; never tie a reward "
            "to a positive one (FTC fake-review rule)",
            "Reply to reviews, critical ones included, and keep the facts current",
        ]
    elif kind == "list":
        branch, category, control, effort, speed, evidence = (
            "earned", "third_party", "earn", "weeks", "months", "moderate")
        why = WHY["earned"]
        title = f"Get onto the {domain} list{'s' if len(lists) != 1 else ''} AI cites"
        steps = [
            "Open each page and check its date and author: lists refreshed every year take "
            "additions; a one-off article rarely changes",
            "Find out how products get on it (the writer's own testing, a submission form, "
            "or an affiliate programme) and use that route",
            "Send the writer something usable: current pricing, a trial account, original "
            "data, or a customer they can quote",
            "Disclose any paid placement; undisclosed pay-to-play is a spam risk",
            "If there is no route in, drop it and publish your own honest comparison "
            "instead",
        ]
    elif kind == "article":
        branch, category, control, effort, speed, evidence = (
            "press", "third_party", "earn", "weeks", "months", "moderate")
        why = WHY["earned"]
        directness = 0.5  # a published article isn't edited to add a brand
        title = f"Give {domain} a reason to cover you"
        text += " These are articles, not lists, so they won't be edited to add you."
        steps = [
            "Don't ask to be added to a published article: it rarely happens",
            "Note the writers and the angle of the cited pieces: they show what this "
            "outlet covers in your category",
            "Bring them something new when you have it: original data, a launch with "
            "numbers, or a customer story",
            "Re-check next month: cited articles turn over quickly, so only keep chasing "
            "outlets that stay cited",
        ]
    elif kind == "community":
        branch, category, control, effort, speed, evidence = (
            "community", "community", "influence", "hours", "weeks", "emerging")
        why = WHY["community"]
        title = f"Answer the {domain} threads AI quotes"
        steps = [
            "Open each cited thread: if it is archived or locked, skip it",
            "Where the question is still open, answer as a disclosed company account, with "
            "specifics: prices, limits, and who you are not right for",
            "No sock puppets and no staff posing as customers: it gets removed and can get "
            "the brand banned",
            "Newer threads are cited more than old ones: answer new questions on the same "
            "topic as they appear",
        ]
    elif kind == "video":
        branch, category, control, effort, speed, evidence = (
            "video", "community", "own", "weeks", "months", "emerging")
        why = WHY["community"]
        directness = 0.5  # your own video still has to be the one that gets cited
        title = f"Publish video answers where AI cites {domain}"
        steps = [
            "You can't get into someone else's video, so make your own for these questions: "
            "one question per video, the question as the title, the answer in the first "
            "30 seconds",
            "Add chapters and a full description: engines read the transcript and the "
            "description, not the pictures",
            "Paying a creator to feature you is advertising and has to be disclosed as such",
        ]
    elif kind == "reference":
        branch, category, control, effort, speed, evidence = (
            "reference", "third_party", "influence", "days", "months", "moderate")
        why = WHY["reference"]
        directness = 0.5
        title = "Check your Wikipedia and Wikidata entries"
        steps = [
            "Check whether you have an entry at all. Without independent press coverage "
            "you won't pass Wikipedia's notability bar, so skip this until you do",
            "If the entry exists, check its facts and propose fixes on the article's talk "
            "page with independent sources",
            "Don't edit your own article or pay for undisclosed edits: both break "
            "Wikipedia's rules and get reverted",
            "Create or correct the Wikidata item: name, website, industry, founding date",
        ]
    else:  # listing
        branch, category, control, effort, speed, evidence = (
            "listing", "platforms", "own", "days", "weeks", "emerging")
        why = WHY["earned"]
        title = f"Fix your listing on {domain}"
        steps = [
            "Check the listing exists and matches your site: name, price, sizes, "
            "availability",
            "Fill in every attribute the listing offers; engines read listings as "
            "structured facts",
            "Ask buyers for reviews on the listing itself (never reward positive ones)",
        ]
    if on_page and kind in ("review", "list", "listing"):
        steps.insert(0, already)
        directness *= 0.7
    p = Play(f"source:{domain}", branch, title, text, 0, evidence, why, steps,
             link="/dashboard/citations", category=category, control=control,
             effort=effort, speed=speed, targets=targets)
    return _rank(p, uni, reach=reach, directness=directness)


def _source_plays(
    session: Session, tenant_id: int, uni: Universe | None = None
) -> list[Play]:
    uni = uni or Universe(session, tenant_id)
    stats = _source_stats(session, tenant_id, uni)
    if not stats:
        return []
    urls = [u for s in stats for u, _n in s["pages"]]
    crawled = {
        row.url: row for row in session.exec(
            select(PagePresence).where(PagePresence.tenant_id == tenant_id,
                                       PagePresence.status == "ok",
                                       col(PagePresence.url).in_(urls))
        ).all()
    }
    plays = sorted((_source_play(s, uni, crawled) for s in stats),
                   key=lambda p: (-p.impact["score"], p.gap_ref))
    kept: list[Play] = []
    per_kind: Counter[str] = Counter()
    for p in plays:
        if per_kind[p.branch] >= MAX_PER_SOURCE_KIND or len(kept) >= MAX_SOURCE_PLAYS:
            continue
        per_kind[p.branch] += 1
        kept.append(p)
    return kept


SITE_SEARCH_MIN = 5  # rival site searches before the gap is worth a play


def _site_search_play(
    session: Session, tenant_id: int, uni: Universe | None = None
) -> list[Play]:
    """Engines check rivals' sites far more often than yours while answering."""
    from api.site_search_service import site_searches

    s = site_searches(session, tenant_id)
    if not s["has_domains"] or s["rivals"] < SITE_SEARCH_MIN or s["rivals"] < 2 * s["owned"]:
        return []
    uni = uni or Universe(session, tenant_id)
    rivals = [t for t in s["targets"] if t["kind"] == "competitor"][:3]
    asks = [a for t in rivals for a in t["top_asks"]][:4]
    p = Play(
        "site_search:rivals", "owned",
        "Engines check facts on your rivals' sites far more than on yours",
        f"While answering your questions, engines searched inside "
        f"{_join([t['name'] for t in rivals])}'s sites {s['rivals']} times and inside yours "
        f"{s['owned']} "
        f"time{'s' if s['owned'] != 1 else ''} in the last {s['days']} days."
        + (f" They looked for {_join([f'“{a}”' for a in asks], 4)}." if asks else ""),
        0, "moderate", WHY["site_search"],
        ["Check each thing they look up on rivals' sites, and make sure a page on your site "
         "answers it plainly in the first lines",
         "Put prices, plans and policies in page text with an updated date, not only in "
         "images or scripts",
         "Confirm the AI search bots can reach those pages (AI Agents tab)"],
        link="/dashboard/pages", category="content", control="own", effort="days",
        speed="weeks",
        targets=[{"kind": "Looked up on a rival's site", "label": a} for a in asks])
    # Site-limited searches are a ChatGPT behaviour (WHY["site_search"]).
    return [_rank(p, uni, uni.for_families(("chatgpt",)), directness=0.25, floor=0.4)]


RESEARCH_MIN = 3  # research citations before the play fires
RESEARCH_SHARE = 0.08  # ...and at least this share of all citations


def _research_play(
    session: Session, tenant_id: int, uni: Universe | None = None
) -> list[Play]:
    """Studies and official data are a real share of what answers cite here."""
    from api.dashboards_service import _latest_results_by_variant
    from engine.processing.citations import classify_source_type

    latest = _latest_results_by_variant(session, tenant_id, ResultVariant.search,
                                        scope="competitive")
    ids = [r.id for r in latest.values() if r.id is not None]
    if not ids:
        return []
    domains = session.exec(
        select(col(Citation.domain)).where(col(Citation.result_id).in_(ids))
    ).all()
    research = Counter(d for d in domains if classify_source_type(d) == "research")
    n = sum(research.values())
    if n < RESEARCH_MIN or n < RESEARCH_SHARE * len(domains):
        return []
    uni = uni or Universe(session, tenant_id)
    top = [d for d, _c in research.most_common(4)]
    p = Play(
        "sources:research", "evidence", "Back your claims with primary evidence",
        f"Answers to your questions cite studies and official data: {_join(top, 4)} "
        f"({n} of {len(domains)} citations). Engines tend to cite the original source of a "
        "fact over pages that summarize it.",
        0, "moderate", WHY["research"],
        ["On pages that make a claim (ingredients, results, safety, prices), link the study "
         "or official source behind it, and say what it found in plain words",
         "Publish your own data where you have it: tests, surveys, product data, with "
         "method and date",
         "Don't overstate what a study shows; health and safety claims need review before "
         "publishing"],
        link="/dashboard/citations", category="content", control="own", effort="days",
        speed="weeks",
        targets=[{"kind": "Primary source cited", "label": d,
                  "detail": f"{research[d]}×"} for d in top])
    cited = {rid for rid, domain, _url, _cat in _citations(session, uni)
             if domain and classify_source_type(domain) == "research"}
    return [_rank(p, uni, cited, directness=0.4, floor=0.3)]


# Muse steps, shared: the Meta AI play carries the first two for brands that
# sell products (Muse shops on top of the same model), the Muse play all.
_MUSE_STEPS = [
    "If you sell products: get stocked by well-known retailers and check they list "
    "you correctly. Muse reportedly ranks well-known merchants first and checks at "
    "most three web stores per request",
    "Grow searches for your brand by name: when a shopper names a brand, Muse "
    "reportedly puts that brand's own store first",
    "Make the product pages Muse lands on easy to read: price, stock, sizes and "
    "shipping in plain text on the page, not only in images or scripts",
    "If you're eligible, turn on agentic checkout for your Meta catalog: Muse's "
    "in-chat checkout reportedly covers only flagged catalog products",
]


def _meta_play(session: Session, tenant_id: int, uni: Universe | None = None) -> list[Play]:
    """A Meta engine names the brand less often than the other engines' answers
    do: Meta AI (measured by API) or Muse (imported captures)."""
    from api.dashboards.measurement import mention_rates
    from engine.processing.stats import change_verdict

    engines = mention_rates(session, tenant_id)["engines"]
    meta_codes = {SurfaceCode.meta_api, SurfaceCode.meta_muse}
    # Meta's answers aren't forced to search, so compare them with what users get
    # elsewhere: the unforced answers of engines that are forced to search.
    others = [e["unforced"] for e in engines
              if e["surface"] not in meta_codes and e.get("unforced")]
    k, n = sum(u["mentioned"] for u in others), sum(u["answers"] for u in others)
    plays: list[Play] = []
    for e in engines:
        if e["surface"] not in meta_codes or not n:
            continue
        if change_verdict(k, n, e["mentioned"], e["answers"])["verdict"] != "down":
            continue
        uni = uni or Universe(session, tenant_id)
        surface = str(e["surface"])
        ids = uni.where(lambda a, s=surface: a.surface == s)
        rest = f"the other engines do in {round(100 * k / n, 1)}%."
        if e["surface"] == SurfaceCode.meta_api:
            p = Play(
                "meta:gap", "meta", "Close the gap on Meta AI",
                f"Meta AI names you in {e['rate']}% of its answers "
                f"({e['answers']} answers); {rest}",
                0, "emerging", WHY["meta"],
                ["Check robots.txt and your CDN let meta-webindexer crawl the site (AI "
                 "Agents tab shows whether it visits)",
                 "Keep your Facebook and Instagram business pages current: products, "
                 "prices, hours and a link to the matching page on your site",
                 "If you sell online, check your products reach Meta: a catalog in "
                 "Commerce Manager, or the Meta channel in Shopify's Agentic Storefronts",
                 *_MUSE_STEPS[:2]],
                link="/dashboard/engines", category="platforms", control="own",
                effort="days", speed="weeks")
        else:
            p = Play(
                "meta:muse_gap", "meta", "Close the gap on Muse",
                f"Muse names you in {e['rate']}% of the imported answers "
                f"({e['answers']} answers); {rest}",
                0, "emerging", WHY["muse"],
                [*_MUSE_STEPS,
                 "Check robots.txt and your CDN don't block Meta-ExternalFetcher, which "
                 "fetches pages when a user's request needs them"],
                link="/dashboard/engines", category="platforms", control="own",
                effort="days", speed="weeks")
        plays.append(_rank(p, uni, ids, directness=0.5, floor=0.3))
    return plays


def _owned_docs_play(
    session: Session, tenant_id: int, plan: dict, uni: Universe | None = None
) -> list[Play]:
    """ChatGPT shifted to searching inside brand sites in August 2026; if its
    answers rarely cite the brand's own pages, the help/docs/pricing pages are
    the cheapest lever for that engine."""
    from api.dashboards_service import _latest_results_by_variant

    # Agent coding prompts count here: they are where docs get cited most.
    latest = _latest_results_by_variant(session, tenant_id, ResultVariant.search,
                                        scope="unbranded")
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
    uni = uni or Universe(session, tenant_id)
    p = Play(
        "owned:chatgpt_docs", "owned",
        "Make your help, docs and pricing pages ChatGPT-ready",
        ("None" if share == 0 else f"Only {round(100 * share)}%")
        + " of ChatGPT's citations on your questions point at your own site, and help "
        "centers and product docs are the brand pages it now cites most.",
        0, "moderate",
        "In August 2026 ChatGPT began searching inside brand sites much more often while "
        "citing Reddit far less; help centers and product docs took those slots (Otterly "
        "and Qwairy tracking, August 2026).",
        ["Make sure help-center, docs and pricing pages are public, crawlable HTML",
         "One page per real customer question, answer first, facts explicit",
         "Keep plan names, prices and limits identical across pricing, docs and help"],
        link="/dashboard/citations", category="content", control="own", effort="days",
        speed="weeks")
    # A site-wide habit, not a fix aimed at particular answers.
    return [_rank(p, uni, uni.for_families(("chatgpt",)), directness=0.2, floor=0.4)]


def _strategy_play(session: Session, tenant_id: int) -> list[Play]:
    """One pinned line of framing, not a ranked task: what to concentrate on
    given how often the brand is named at all."""
    from api.dashboards_service import mention_rates

    overall = mention_rates(session, tenant_id).get("overall") or {}
    n, rate = overall.get("answers", 0), overall.get("rate", 0.0)
    if n < 30:
        return []
    if rate < 20:
        title, text, steps = (
            "Focus: get found at all",
            f"You're named in {rate}% of answers on your category questions. Engines aren't "
            "finding you yet, so on-page polish won't move much.",
            ["Make sure every AI search bot can reach the site (AI Agents tab)",
             "Cover the sub-questions engines search on your own pages, with prices and "
             "dates stated plainly (Fan-out tab)",
             "Then get onto the third-party lists, reviews and directories engines "
             "already cite"])
    elif rate < 70:
        title, text, steps = (
            "Focus: turn mentions into recommendations",
            f"You're named in {rate}% of answers. Being named is not the same as being "
            "recommended, so work on how you're positioned for each type of buyer.",
            ["Check which personas and questions name rivals first (Personas tab)",
             "Publish honest comparisons that say who you're best for",
             "Close rating gaps on the review sites engines cite"])
    else:
        title, text, steps = (
            "Focus: defend accuracy and freshness",
            f"You're named in {rate}% of answers. The risk now is engines getting your "
            "facts wrong or citing stale pages.",
            ["Keep the fact sheet current so accuracy checks catch errors (Brand tab)",
             "Refresh any page that loses a citation within a week",
             "Watch for rivals gaining on the questions you lead"])
    return [Play("strategy", "strategy", title, text, 100, "moderate", WHY["strategy"],
                 steps, link="/dashboard")]


def _own_page_plays(
    session: Session, tenant_id: int, uni: Universe | None = None,
    uni_all: Universe | None = None,
) -> list[Play]:
    from api.own_pages_service import own_pages

    rep = own_pages(session, tenant_id)
    plays: list[Play] = []
    cited_by = _own_page_answers(session, uni_all) if uni_all is not None else {}

    def citing(path: str) -> Reach | None:
        """Answers that cite this page: all of them are at stake."""
        if uni_all is None:
            return None
        return uni_all.reach(cited_by.get(path, ()), problem=lambda _a: True)

    def basis(reach: Reach | None, otherwise: str, many: bool = False) -> str:
        if reach is not None and reach.answers:
            return (f"{reach.answers} answers in the last 28 days cite "
                    f"{'these pages' if many else 'this page'} "
                    f"({engines_phrase(reach.families)}).")
        return otherwise

    for r in rep["pages"]:
        if not r["fact_conflicts"]:
            continue
        c = r["fact_conflicts"][0]
        rule = c.get("label") or (
            f"never say “{c['expected']}”" if _is_disallowed(c)
            else f"{c['subject']} is {c['expected']}")
        said = (f"“{c['stated']}”" if _is_disallowed(c)
                else f"{c['subject']} is {c['stated']}")
        p = Play(
            f"own_page:facts:{r['path']}", "own_page",
            f"Your own page contradicts your fact sheet: {r['path']}",
            f"{r['path']} says {said}; your fact sheet: {rule}. AI answers read this page"
            + (f" (cited {r['cited']}× lately)." if r["cited"] else "."),
            0, "moderate", WHY["own_pages"],
            ["Correct the statement on the page (or the fact sheet, if the page is right)",
             "Show an 'Updated <month year>' date on the page", _RECRAWL],
            link="/dashboard/pages", category="accuracy", control="own", effort="hours",
            speed="weeks")
        reach = citing(r["path"])
        plays.append(_rank(p, uni_all, reach=reach, severity=1.5, floor=1.2, at_stake=True,
                           basis=basis(reach, "Your own page states something your fact "
                                              "sheet says is wrong.")))
    for r in rep["pages"]:
        if "noindex" in r["flags"]:
            p = Play(
                f"own_page:noindex:{r['path']}", "own_page",
                f"Remove noindex from {r['path']}",
                f"{r['path']} carries a noindex tag, so Google, Bing and Brave drop it from "
                "their indexes and no engine that searches can retrieve it"
                + (f", though answers cited it {r['cited']}× lately." if r["cited"] else "."),
                0, "official", WHY["crawler"],
                ["Remove the noindex meta tag or X-Robots-Tag header from the page",
                 "Check the page's canonical points at itself", _RECRAWL],
                link="/dashboard/pages", category="structure", control="own",
                effort="hours", speed="days")
            reach = citing(r["path"])
            plays.append(_rank(p, uni_all, reach=reach, floor=0.8, at_stake=True,
                               basis=basis(reach, "No engine that searches can retrieve "
                                                  "this page while the tag is there.")))
        elif "not in Brave" in r["flags"]:
            p = Play(
                f"own_page:brave:{r['path']}", "own_page",
                f"Submit {r['path']} to Brave",
                f"Brave Search, which Claude's web search runs on, doesn't return {r['path']} "
                "for its own URL, so Claude can't cite it"
                + (f"; other engines cited it {r['cited']}× lately." if r["cited"] else "."),
                0, "moderate", WHY["crawler"],
                ["Confirm Googlebot can crawl the page (URL Inspection in Search Console): "
                 "Brave's crawler follows Googlebot's rules",
                 "Submit the exact URL on Brave's 'Brave Search crawler' help page",
                 "Link to the page from related product and resource pages",
                 "Re-check with site:yourdomain \"page title\" on search.brave.com after a week"],
                link="/dashboard/pages", category="structure", control="own",
                effort="hours", speed="weeks")
            # One page on one engine: Claude's answers, lightly.
            ids = uni.for_families(("claude",)) if uni is not None else None
            plays.append(_rank(p, uni, ids, directness=0.1, floor=0.4,
                               basis="Claude can't cite this page until Brave holds it."))
    weak = [r for r in rep["pages"]
            if {"unreachable", "stale", "errors for AI bots"} & set(r["flags"])]
    if weak:
        paths = [r["path"] for r in weak]
        p = Play(
            "own_page:health", "own_page",
            f"Fix {len(weak)} of your own pages AI answers rely on",
            f"{_join(paths, 4)}" + (f" and {len(paths) - 4} more" if len(paths) > 4 else "")
            + " are unreachable, erroring for AI bots, or show no sign of being current.",
            0, "moderate", WHY["own_pages"],
            ["Fix errors and redirects first: an engine can't quote a page it can't load",
             "Refresh numbers and examples; add a visible 'Updated <month year>'",
             "Keep plan names and prices identical across pricing, docs and help pages"],
            link="/dashboard/pages",
            category=("structure" if any({"unreachable", "errors for AI bots"} & set(r["flags"])
                                         for r in weak) else "content"),
            control="own", effort="days", speed="weeks",
            targets=[{"kind": "Your page", "label": r["path"],
                      "note": _join([f for f in r["flags"]
                                     if f in ("unreachable", "stale", "errors for AI bots")], 3),
                      "detail": f"cited {r['cited']}×" if r["cited"] else ""}
                     for r in weak[:8]])
        reach = (uni_all.reach({i for path in paths for i in cited_by.get(path, ())},
                               problem=lambda _a: True) if uni_all is not None else None)
        plays.append(_rank(p, uni_all, reach=reach, directness=0.6, floor=0.4,
                           at_stake=True,
                           basis=basis(reach, "AI answers rely on these pages; none cited "
                                              "them in the last 28 days.", many=True)))
    return plays


def _model_change_plays(session: Session, tenant_id: int) -> list[Play]:
    """A notice, not a task: it changes how to read the numbers."""
    from api.answer_shape_service import model_timeline

    recent = (datetime.now(UTC) - timedelta(days=21)).date().isoformat()
    plays = []
    for ch in model_timeline(session, tenant_id):
        if ch["since"] < recent:
            continue
        plays.append(Play(
            f"model_change:{ch['surface']}:{ch['model']}", "model_change",
            f"{ch['label']} switched to {ch['model']}",
            f"Since {ch['since']}, {ch['label']} answers with {ch['model']}. Search and "
            "citing behaviour can shift overnight with a new model.",
            _SETUP_PRIORITY, "strong", WHY["model_change"],
            ["Open Answer Shape and compare this engine before and after the switch",
             "Hold off judging content changes shipped around this date until a few "
             "runs on the new model are in"],
            link="/dashboard/answers", category="setup"))
    return plays


# Setup plays and notices carry no projected impact; they sort under every
# ranked play and the page lists them apart.
_SETUP_PRIORITY = 0


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
    "sources": {"reviews", "earned", "press", "community", "video", "reference", "listing"},
    "owned_docs": {"owned"},
    "strategy": {"strategy"},
    "own_pages": {"own_page"},
    "model_change": {"model_change"},
    "site_search": {"owned"},
    "research": {"evidence"},
    "meta": {"meta"},
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
    # The measured answers every play is ranked against: the headline's
    # population, and everything (branded questions too) for the plays about
    # the brand's own pages and facts. Without them plays still generate,
    # ranked by their floors.
    uni: Universe | None
    uni_all: Universe | None
    try:
        with session.begin_nested():
            uni = Universe(session, tenant_id)
            uni_all = Universe(session, tenant_id, scope="all")
    except Exception:  # noqa: BLE001
        log.exception("recommendations: answer universe failed")
        uni = uni_all = None

    frozen: set[str] = set()
    if not plan_d:
        frozen |= _SOURCE_BRANCHES["refresh"]
    plays: list[Play] = _run_source(
        session, "query", lambda: _query_plays(session, tenant_id, plan_d, uni), frozen)
    # Questions with a page play carry their sub-questions on it.
    covered = frozenset(p.query_text for p in plays if p.branch in ("web_search", "aio"))
    sources: list[tuple[str, Callable[[], list[Play]]]] = [
        ("accuracy", lambda: _accuracy_plays(session, tenant_id, uni_all)),
        ("agents", lambda: _agent_plays(session, tenant_id, uni, uni_all)),
        ("refresh", lambda: _refresh_plays(plan_d, uni, session)),
        ("subquery", lambda: _subquery_plays(session, tenant_id, uni, covered)),
        ("sources", lambda: _source_plays(session, tenant_id, uni)),
        ("owned_docs", lambda: _owned_docs_play(session, tenant_id, plan_d, uni)),
        ("site_search", lambda: _site_search_play(session, tenant_id, uni)),
        ("research", lambda: _research_play(session, tenant_id, uni)),
        ("meta", lambda: _meta_play(session, tenant_id, uni)),
        ("strategy", lambda: _strategy_play(session, tenant_id)),
        ("own_pages", lambda: _own_page_plays(session, tenant_id, uni, uni_all)),
        ("model_change", lambda: _model_change_plays(session, tenant_id)),
    ]
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
    # Bands are relative to the live list: plays a person already closed by
    # hand don't take a share of it.
    hand_closed = {ref for ref, r in existing.items() if r.status in HAND_STATUSES}
    assign_bands([p.impact for p in plays if p.impact and p.gap_ref not in hand_closed])
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
        rec.category, rec.control, rec.effort, rec.speed = (
            p.category, p.control, p.effort, p.speed)
        rec.impact, rec.targets = dict(p.impact), list(p.targets)
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
        # Plays a person added by hand have no signal to resolve them.
        if rec.branch == "manual" or rec.branch in frozen or rec.gap_ref in still_lost:
            open_count += 1
            continue
        rec.status = RecommendationStatus.resolved
        rec.updated_at = utcnow()
        session.add(rec)
    session.commit()
    return open_count


def _is_disallowed(c: dict) -> bool:
    """A conflict with a 'must never say' fact. Older crawl rows carry no
    kind: they are disallowed when the stated text is the forbidden phrase."""
    if c.get("kind"):
        return c["kind"] == "disallowed"
    return str(c.get("stated", "")).lower() in str(c.get("expected", "")).lower()
