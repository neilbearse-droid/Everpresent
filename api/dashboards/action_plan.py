"""Action Plan: contestability, lost citations, the citability diff and briefs."""

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, col, select

from api.dashboards.common import (
    _as_utc,
    _brand_name,
    _latest_results_by_variant,
    _off_score_query_texts,
    _owned_domains,
    _surface_label,
)
from api.dashboards.engines import engine_scorecard
from api.dashboards.fanout import _fanout_by_query
from api.models import (
    Citation,
    Intervention,
    Mention,
    PagePresence,
    Query,
    QueryClassification,
    Result,
    ResultVariant,
)
from engine.processing.citations import domain_is_owned

# Retrieval-dependence weight per classification bucket: a query the engine
# answers from live search is winnable with citable content; a training-locked
# answer is a long game regardless of what you publish.
_DEPENDENCE_WEIGHT = {"very_likely": 1.0, "likely": 0.75, "possible": 0.5, "unlikely": 0.25}


CONTEST_WINDOW_DAYS = 60


def _contestability(session: Session, tenant_id: int, query_texts: set[str]) -> dict[str, dict]:
    """Contestability = answer volatility × retrieval dependence, per query.

    Volatility is churn in WHICH brands an answer names, run over run (per
    surface, then averaged): when the named set keeps changing, the engine's
    retrieval is still shopping and fresh content can win it now; when the same
    brands come back every time, it's locked in. (Answer wording changes on
    nearly every run, so text churn would call everything volatile.) Uses the
    last CONTEST_WINDOW_DAYS. Needs >=2 runs of history to say anything —
    reported honestly as 'needs history' until then."""
    hashes_by_key: dict[tuple[str, str], list[frozenset[str]]] = defaultdict(list)
    if not query_texts:
        return {}
    since = datetime.now(UTC) - timedelta(days=CONTEST_WINDOW_DAYS)
    conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == ResultVariant.search,
        Result.status == "ok",
        col(Result.query_text).in_(query_texts),
        col(Result.created_at) >= since,
    ]
    named: dict[int, set[str]] = defaultdict(set)
    for rid, name in session.exec(
        select(col(Mention.result_id), col(Mention.entity_name))
        .join(Result, col(Result.id) == col(Mention.result_id))
        .where(*conds)
    ).all():
        named[rid].add(name.lower())
    for rid, query_text, surface in session.exec(
        select(col(Result.id), col(Result.query_text), col(Result.surface))
        .where(*conds)
        .order_by(col(Result.id))
    ).all():
        if rid is not None:
            hashes_by_key[(query_text, str(surface))].append(frozenset(named.get(rid, set())))

    dependence_by_query: dict[str, list[float]] = defaultdict(list)
    for c in session.exec(
        select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
    ).all():
        if c.query_text in query_texts:
            dependence_by_query[c.query_text].append(
                _DEPENDENCE_WEIGHT.get(c.web_search_likelihood, 0.5)
            )

    out: dict[str, dict] = {}
    for q in query_texts:
        churns: list[float] = []
        for (qt, _s), hashes in hashes_by_key.items():
            if qt != q or len(hashes) < 2:
                continue
            transitions = sum(1 for a, b in zip(hashes, hashes[1:], strict=False) if a != b)
            churns.append(transitions / (len(hashes) - 1))
        deps = dependence_by_query.get(q) or [0.5]
        dependence = sum(deps) / len(deps)
        if not churns:
            out[q] = {"score": None, "label": "needs history",
                      "volatility": None, "dependence": round(dependence, 2)}
            continue
        volatility = sum(churns) / len(churns)
        score = round(100 * volatility * dependence)
        label = "winnable now" if score >= 50 else ("contested" if score >= 20 else "locked in")
        out[q] = {"score": score, "label": label,
                  "volatility": round(volatility, 2), "dependence": round(dependence, 2)}
    return out


def _page_url(url: str, owned: list[str]) -> str | None:
    """The brand page a citation points at, normalized so tracking variants
    (?utm_source=chatgpt.com, #fragments, trailing slashes) count as one page.
    None when the link's own host isn't a brand domain: engines like Gemini
    cite through redirect URLs labelled with the brand's domain, which can't
    be refreshed or diffed as pages."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if not host or not domain_is_owned(host, owned):
        return None
    path = parts.path.rstrip("/") or "/"
    # One page however it was linked: http/https and www. variants collapse.
    return f"https://{host.removeprefix('www.')}{path}"


def _lost_citations(session: Session, tenant_id: int) -> dict:
    """Lost-Citation Radar (§focus-group #4): run-over-run diff of the brand's
    OWN cited pages. Losing a citation is the earliest actionable decay signal,
    and the proven fix is cheap — refresh the page's dates, stats, and examples.
    Compares the last two runs that produced brand-page citations."""
    # The last two runs that measured anything (competitive queries), whether
    # or not they produced brand citations: a run that lost EVERY brand
    # citation is exactly the one this radar exists to catch.
    branded = _off_score_query_texts(session, tenant_id)
    owned = _owned_domains(session, tenant_id)
    base: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == ResultVariant.search,
        Result.status == "ok",
    ]
    if branded:
        base.append(col(Result.query_text).not_in(branded))
    # Only the last two measured runs matter; don't load the whole history.
    last_two = session.exec(
        select(col(Result.run_id)).where(*base)
        .group_by(col(Result.run_id)).order_by(col(Result.run_id).desc()).limit(2)
    ).all()
    result_ctx: dict[int, tuple[int, str]] = {}
    measured: dict[int, set[str]] = defaultdict(set)
    if last_two:
        for rid, run_id, query_text in session.exec(
            select(col(Result.id), col(Result.run_id), col(Result.query_text)).where(
                *base, col(Result.run_id).in_(last_two)
            )
        ).all():
            if rid is None:
                continue
            result_ctx[rid] = (run_id, query_text)
            measured[run_id].add(query_text)
    by_run: dict[int, set[tuple[str, str]]] = defaultdict(set)
    domain_of: dict[str, str] = {}
    for c in session.exec(
        select(Citation).where(
            Citation.tenant_id == tenant_id,
            Citation.source_category == "brand",
            col(Citation.result_id).in_(list(result_ctx) or [-1]),
        )
    ).all():
        ctx = result_ctx.get(c.result_id)
        if ctx is None:
            continue
        url = _page_url(c.url, owned)
        if url is None:
            continue  # a redirect wrapper (e.g. Gemini grounding), not a brand page
        run_id, query_text = ctx
        by_run[run_id].add((url, query_text))
        domain_of[url] = c.domain

    run_ids = sorted(measured)
    if len(run_ids) < 2:
        latest = by_run[run_ids[-1]] if run_ids else set()
        return {"ready": False, "lost": [], "held": len(latest), "gained": 0,
                "latest_cited": sorted({url for url, _q in latest})}
    prev_id, latest_id = run_ids[-2], run_ids[-1]
    # Compare only queries BOTH runs measured, so a partial run doesn't
    # report everything it skipped as "lost".
    shared = measured[prev_id] & measured[latest_id]
    prev_set = {pair for pair in by_run[prev_id] if pair[1] in shared}
    latest_set = {pair for pair in by_run[latest_id] if pair[1] in shared}
    lost_pairs = prev_set - latest_set
    latest_urls: dict[str, int] = defaultdict(int)
    for url, _q in latest_set:
        latest_urls[url] += 1

    lost_by_url: dict[str, list[str]] = defaultdict(list)
    for url, query in sorted(lost_pairs):
        lost_by_url[url].append(query)
    return {
        "ready": True,
        # Every brand page the latest run cited (any query): a lost page only
        # counts as won back once it shows up here again.
        "latest_cited": sorted({url for url, _q in by_run[latest_id]}),
        "lost": [
            {"url": url, "domain": domain_of.get(url, ""), "queries": queries,
             "still_cited_on": latest_urls.get(url, 0)}
            for url, queries in sorted(lost_by_url.items(), key=lambda kv: -len(kv[1]))
        ],
        "held": len(prev_set & latest_set),
        "gained": len(latest_set - prev_set),
    }


_MAX_DIFF_WINNERS = 3


def _citability_diff(
    winners: list[PagePresence], your_page: PagePresence | None
) -> dict:
    """Citability fingerprint diff (§focus-group #3): what the winning cited
    pages share, and where your page falls short — ordered by the 2026
    evidence. Explicit facts (prices, update dates, ratings, current-year
    information) and evidence density come first: controlled studies show they
    change whether a page is cited. Formatting (answer capsules, front-loading,
    quotations) comes after: it shifts credit among pages already retrieved,
    so it can't rescue a page the engine never picks up. Markup is hygiene."""
    if not winners:
        return {"ready": False}
    half = len(winners) / 2

    def common(key: str) -> bool:
        return sum(1 for w in winners if (w.features or {}).get(key)) >= half

    def median(key: str) -> int:
        vals = sorted((w.features or {}).get(key, 0) for w in winners)
        return vals[len(vals) // 2]

    spec = {
        # Explicit facts (strongest controlled evidence).
        "has_price": common("has_price"),
        "has_updated_date": common("has_updated_date"),
        "has_rating": common("has_rating"),
        "latest_year": median("latest_year"),
        # Evidence density.
        "statistic_count": median("statistic_count"),
        "word_count": median("word_count"),
        # Second-order formatting.
        "has_answer_capsule": common("has_answer_capsule"),
        "front_loaded": common("front_loaded"),
        "quotations": common("quotation_count"),
        "citation_count": median("citation_count"),
        "promotional_tone_score": median("promotional_tone_score"),
        # Hygiene (entity legibility, not citation levers).
        "json_ld": common("json_ld"),
        "faq_schema": common("faq_schema"),
        "has_tables": common("has_tables"),
        "recent_year_mentions": median("recent_year_mentions"),
    }

    gaps: list[str] = []
    if your_page is None:
        gaps.append(
            "None of your pages is cited on this query. First make sure one answers it "
            "AND the sub-questions engines search for it (see the brief), then build one "
            "to the winning spec below"
        )
    else:
        yf = your_page.features or {}
        # 1. Explicit facts.
        if spec["has_price"] and not yf.get("has_price"):
            gaps.append(
                "Winning pages state prices outright; yours doesn't. Put current plan "
                "prices on the page as text (explicit prices raised citation odds in a "
                "large 2026 controlled study)"
            )
        if spec["has_updated_date"] and not yf.get("has_updated_date"):
            gaps.append(
                "Winning pages show when they were last updated; yours doesn't. Add a "
                "visible 'Updated <month year>' plus dateModified, and keep it honest "
                "(recent timestamps raised citation odds in controlled tests)"
            )
        your_year = yf.get("latest_year", 0)
        if spec["latest_year"] and your_year and your_year < spec["latest_year"]:
            gaps.append(
                f"Winning pages cite {spec['latest_year']} facts; your newest is "
                f"{your_year}. Refresh the numbers, examples and dates (most cited pages "
                f"were updated in the past year)"
            )
        if spec["has_rating"] and not yf.get("has_rating"):
            gaps.append(
                "Winning pages show ratings or review scores; yours doesn't. Surface your "
                "real review rating and where it comes from (small rating gaps flipped "
                "AI recommendations in a 2026 controlled test)"
            )
        # 2. Evidence density.
        if spec["statistic_count"] >= 5 and yf.get("statistic_count", 0) < max(
            3, spec["statistic_count"] // 2
        ):
            gaps.append(
                f"Winning pages carry ~{spec['statistic_count']} statistics/data points; "
                f"yours has {yf.get('statistic_count', 0)}. Add specific, verifiable "
                f"figures: engines lean hardest on pages with numbers, definitions and "
                f"comparisons"
            )
        if yf.get("word_count", 0) < spec["word_count"] * 0.5:
            gaps.append(
                f"Winning pages run ~{spec['word_count']} words; yours is "
                f"{yf.get('word_count', 0)}. It's likely too thin to cite"
            )
        # 3. Second-order formatting: helps once retrieved.
        if spec["has_answer_capsule"] and not yf.get("has_answer_capsule"):
            gaps.append(
                "Winning pages open sections with a short direct answer under a question "
                "heading (an answer capsule); yours doesn't. Worth adding, but it only "
                "helps once the page is retrieved"
            )
        if spec["front_loaded"] and not yf.get("front_loaded"):
            gaps.append(
                "Winning pages put the core answer near the top; yours buries it. Move "
                "the answer and key numbers up"
            )
        if spec["quotations"] and not yf.get("quotation_count"):
            gaps.append(
                "Winning pages quote named, credible sources; yours has no quotations. "
                "Add attributed quotes (a lab-tested lever, not yet proven on live engines)"
            )
        if spec["citation_count"] >= 3 and yf.get("citation_count", 0) < max(
            2, spec["citation_count"] // 2
        ):
            gaps.append(
                f"Winning pages cite ~{spec['citation_count']} outside sources; yours "
                f"cites {yf.get('citation_count', 0)}. Link the sources behind your claims"
            )
        if yf.get("promotional_tone_score", 0) > max(6.0, spec["promotional_tone_score"] * 2):
            gaps.append(
                "Your page reads like an ad. Answers lift neutral, factual sentences; "
                "cut the sales language from anything you want cited"
            )
        # 4. Hygiene.
        if spec["json_ld"] and not yf.get("json_ld"):
            gaps.append("Add JSON-LD structured data (entity hygiene, not a ranking lever)")
        if spec["has_tables"] and not yf.get("has_tables"):
            gaps.append("Winning pages use comparison tables; yours has none")
        if not gaps:
            gaps.append(
                "Your page matches the winning fingerprint. The gap is likely retrieval "
                "(sub-query coverage) or third-party proof (reviews, mentions), not the page"
            )

    return {
        "ready": True,
        "winners": [w.url for w in winners],
        "spec": spec,
        "your_page": (
            {"url": your_page.url, "features": your_page.features} if your_page else None
        ),
        "gaps": gaps,
    }


def action_plan(session: Session, tenant_id: int) -> dict:
    """The actionable layer (panel #1 + #4): a citation-gap target list — the
    third-party sources that cite rivals in this vertical but not you — and a
    ready-to-work content brief per gap query. Pure reads; briefs are assembled
    from measured data, no LLM spend."""
    brand_name = _brand_name(session, tenant_id)
    owned = _owned_domains(session, tenant_id)

    # Latest search result per (query, surface) and its mention context.
    # Competitive only: branded answers cite the brand's own site and would
    # make targets look "already citing you".
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, scope="competitive"
    )
    fanout_by_query = _fanout_by_query(search)
    results_by_id = {r.id: r for r in search.values() if r.id is not None}
    ids = list(results_by_id)
    brand_ids: set[int] = set()
    comps_by_result: dict[int, set[str]] = defaultdict(set)
    if ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            if m.entity_type == "brand":
                brand_ids.add(m.result_id)
            else:
                comps_by_result[m.result_id].add(m.entity_name)

    # Aggregate third-party ("other") citation domains across those results.
    domain_stats: dict[str, dict] = {}
    per_query_targets: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    # Per-query cited URLs for the citability diff: the winning third-party
    # pages on each query, and the brand's own cited page (if any).
    winning_urls_by_query: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    brand_urls_by_query: dict[str, list[str]] = defaultdict(list)
    if ids:
        for c in session.exec(
            select(Citation).where(Citation.result_id.in_(ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            result = results_by_id.get(c.result_id)
            if result is None:
                continue
            if c.source_category == "brand":
                if c.url not in brand_urls_by_query[result.query_text]:
                    brand_urls_by_query[result.query_text].append(c.url)
                continue
            if c.source_category != "other" or domain_is_owned(c.domain, owned):
                continue  # skip rivals' own sites; keep pitchable third parties
            winning_urls_by_query[result.query_text][c.url] += 1
            comps = comps_by_result.get(c.result_id, set())
            brand_here = c.result_id in brand_ids
            entry = domain_stats.setdefault(
                c.domain,
                {"domain": c.domain, "citations": 0, "queries": set(), "surfaces": set(),
                 "competitor_assoc": 0, "brand_assoc": 0, "example_url": c.url},
            )
            entry["citations"] += 1
            entry["queries"].add(result.query_text)
            entry["surfaces"].add(str(result.surface))
            if comps:
                entry["competitor_assoc"] += 1
            if brand_here:
                entry["brand_assoc"] += 1
            # Per-query targets: sources cited where you're absent but a rival is present.
            if not brand_here and comps:
                per_query_targets[result.query_text][c.domain] |= comps

    targets = [
        {
            "domain": d["domain"],
            "citations": d["citations"],
            "queries": len(d["queries"]),
            "surfaces": sorted(d["surfaces"]),
            "competitor_assoc": d["competitor_assoc"],
            "already_citing_you": d["brand_assoc"] > 0,
            "brand_assoc": d["brand_assoc"],
            "example_url": d["example_url"],
        }
        # Prime targets first: cite rivals, don't yet cite you.
        for d in sorted(
            domain_stats.values(),
            key=lambda d: (d["brand_assoc"] == 0, d["competitor_assoc"], d["citations"]),
            reverse=True,
        )
    ][:25]

    # Content briefs for each gap query, using the scorecard's diagnosis.
    card = engine_scorecard(session, tenant_id)
    queries = list(session.exec(select(Query).where(Query.tenant_id == tenant_id)).all())
    by_corpus: dict[str, list[str]] = defaultdict(list)
    for q in queries:
        if q.active:
            by_corpus[q.corpus_tag].append(q.text)
    corpus_of = {q.text: q.corpus_tag for q in queries}

    briefs = []
    for row in card["matrix"]:
        dtype = row["diagnosis"]["type"]
        if dtype not in ("content_gap", "knowledge_gap"):
            continue
        cells = row["cells"]
        engines_missing = [_surface_label(s) for s, c in cells.items() if c["state"] != "brand"]
        competitors_winning = sorted({name for c in cells.values() for name in c["competitors"]})
        q_targets = [
            {"domain": dom, "rivals": sorted(rivals)}
            for dom, rivals in sorted(
                per_query_targets.get(row["query"], {}).items(),
                key=lambda kv: -len(kv[1]),
            )
        ][:5]
        # Prefer the real fan-out the engines issued for this prompt (§AEO M1);
        # fall back to the same-corpus heuristic when none was observed.
        observed = fanout_by_query.get(row["query"], [])
        heuristic = [t for t in by_corpus.get(corpus_of.get(row["query"], ""), [])
                     if t != row["query"]][:6]
        subtopics = (observed[:8] if observed else heuristic)
        briefs.append({
            "query_id": row["id"],
            "query": row["query"],
            "corpus_tag": row["corpus_tag"],
            "diagnosis": row["diagnosis"],
            "engines_missing": engines_missing,
            "competitors_winning": competitors_winning,
            "target_sources": q_targets,
            "subtopics": subtopics,
            "subtopics_source": "observed" if observed else "heuristic",
            "outline": _brief_outline(row["query"], brand_name, competitors_winning, subtopics),
            "spam_risk": _spam_risk(row["query"]),
        })

    # Citability diff per brief: your page vs the crawled winning pages.
    crawled = {
        row.url: row
        for row in session.exec(
            select(PagePresence).where(
                PagePresence.tenant_id == tenant_id, PagePresence.status == "ok"
            )
        ).all()
    }
    for b in briefs:
        ranked_winners = sorted(
            winning_urls_by_query.get(b["query"], {}).items(), key=lambda kv: -kv[1]
        )
        winners = [crawled[u] for u, _n in ranked_winners if u in crawled][:_MAX_DIFF_WINNERS]
        your_page = next(
            (crawled[u] for u in brand_urls_by_query.get(b["query"], []) if u in crawled),
            None,
        )
        b["citability"] = _citability_diff(winners, your_page)

    # Shipped-state per brief (intervention ledger).
    # Newest ship per query wins (a query can have several interventions).
    shipped_by_query = {
        i.query_text: i
        for i in session.exec(
            select(Intervention)
            .where(Intervention.tenant_id == tenant_id)
            .order_by(Intervention.shipped_at)  # pyright: ignore[reportArgumentType]
        ).all()
    }
    for b in briefs:
        item = shipped_by_query.get(b["query"])
        b["intervention"] = (
            {"id": item.id, "shipped_at": _as_utc(item.shipped_at).date().isoformat(),
             "url": item.url}
            if item is not None
            else None
        )

    # Contestability ranking: spend effort where the answer is still in play.
    scores = _contestability(session, tenant_id, {b["query"] for b in briefs})
    for b in briefs:
        b["contestability"] = scores.get(
            b["query"],
            {"score": None, "label": "needs history", "volatility": None, "dependence": 0.5},
        )
    briefs.sort(
        key=lambda b: (
            b["contestability"]["score"] is None,
            -(b["contestability"]["score"] or 0),
        )
    )
    strike_zone = {"winnable now": 0, "contested": 0, "locked in": 0, "needs history": 0}
    for b in briefs:
        strike_zone[b["contestability"]["label"]] += 1

    return {
        "brand_name": brand_name,
        "targets": targets,
        "briefs": briefs,
        "strike_zone": strike_zone,
        "protect": _lost_citations(session, tenant_id),
        "summary": {
            "target_domains": len(targets),
            "briefs": len(briefs),
            **card["diagnosis_summary"],
        },
    }


# Queries whose natural self-published answer is a ranked "best X" list or an
# "alternatives"/"vs" page — the formats Google's 2026 spam policy and the
# June 2026 spam update targeted (self-promotional listicles, scaled
# alternatives pages). For these, the safe play is earned placement on
# third-party lists, not publishing your own ranking.
_LISTICLE_RE = re.compile(
    r"\b(best|top|cheapest|alternatives?|vs\.?|versus|compare|comparison|which is better)\b",
    re.IGNORECASE,
)


def _spam_risk(query: str) -> dict | None:
    if not _LISTICLE_RE.search(query):
        return None
    return {
        "level": "high",
        "note": (
            "Don't answer this with your own ranked 'best X' list or an "
            "'alternatives' page. It barely works and it's risky: in 2026 experiments, "
            "placement on third-party lists drove far more AI mentions than brands' own "
            "lists, and Google's August and September 2026 spam updates target "
            "self-promotional listicles and attempts to steer AI answers. Earn a place "
            "on the third-party pages engines already cite (target sources), and "
            "publish an honest comparison that says where competitors fit better."
        ),
    }


def _brief_outline(
    query: str, brand: str, competitors: list[str], subtopics: list[str]
) -> list[str]:
    """A content outline in 2026 evidence order: answer the query and the
    sub-questions engines actually search (retrieval first), state hard facts
    explicitly, back them with evidence, then keep it fresh. Deterministic
    scaffolding, not prose."""
    outline = [
        f"H1 + first 100 words: a direct, factual answer to “{query}”",
    ]
    for sub in subtopics[:4]:
        outline.append(f"H2: {sub[0].upper() + sub[1:]} (a sub-question engines search)")
    outline.append(
        f"H2: The facts, stated plainly: {brand}'s current prices, plans, limits and "
        "specs as text (not only in images or behind a click), with the date checked"
    )
    if competitors:
        outline.append(
            f"H2: Honest comparison table vs {', '.join(competitors[:3])}: where each "
            f"fits best, including where {brand} isn't the right pick"
        )
    outline.append(
        "H2: Proof: your real review rating and source, original numbers or customer "
        "data, and named sources for every claim"
    )
    outline.append(
        "Show a visible 'Updated <month year>' and re-check the facts every quarter; "
        "after each update, request a recrawl (IndexNow for Bing/Copilot/ChatGPT, "
        "Search Console for Google)"
    )
    return outline
