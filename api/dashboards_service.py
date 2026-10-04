"""Read-side aggregation for the client dashboards (§7.1 Overview, Personas,
Queries). Pure Postgres reads over the processed rollups — no LLM, no
provider calls."""

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from api.fanout_service import PRIORITY_RANK, shard_norm
from api.fanout_service import names_present as _names_present
from api.models import (
    AccuracyFinding,
    AiReferralDaily,
    BrandFact,
    BrandProfile,
    Citation,
    Competitor,
    ConsultedSource,
    FanoutShard,
    Intervention,
    Mention,
    PagePresence,
    Query,
    QueryClassification,
    Result,
    ResultStatus,
    ResultVariant,
    SurfaceCode,
    Tenant,
    UntrackedMention,
    VisibilityDaily,
)
from engine.processing.citations import classify_source_type, domain_is_owned
from engine.processing.stats import change_verdict, rate_summary

TREND_DAYS = 90
SOV_DAYS = 30
MAX_MOVERS = 8


def _brand_name(session: Session, tenant_id: int) -> str:
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    if brand:
        return brand.brand_name
    tenant = session.get(Tenant, tenant_id)
    return tenant.name if tenant else "Brand"


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _date_window(
    start: str | None, end: str | None
) -> tuple[datetime | None, datetime | None]:
    """Inclusive ISO-date range → UTC datetime bounds (end is exclusive, +1 day).
    Invalid values are ignored rather than erroring — a bad filter should
    degrade to 'all time', not break the dashboard."""

    def parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        # Convert an offset-aware input to UTC; assume UTC for a naive one
        # (don't silently reinterpret an offset as UTC).
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    lo = parse(start)
    hi = parse(end)
    if hi is not None:
        try:
            hi = hi + timedelta(days=1)
        except OverflowError:  # e.g. end=9999-12-31: no upper bound
            hi = None
    return lo, hi


def _utc(dt: datetime) -> datetime:
    """A window bound as aware UTC, the form the datetime columns bind."""
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _in_window(dt: datetime, lo: datetime | None, hi: datetime | None) -> bool:
    d = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return (lo is None or d >= lo) and (hi is None or d < hi)


def _date_in_range(date: str, start: str | None, end: str | None) -> bool:
    """ISO date strings compare lexicographically, so plain string bounds work."""
    return (not start or date >= start) and (not end or date <= end)


def _clean_date(value: str | None) -> str | None:
    """Normalize to a bare YYYY-MM-DD string (or None if unparseable). Callers
    string-compare these against stored `date` columns, so a datetime input
    like '2026-07-01T00:00:00' must be truncated — otherwise the lexicographic
    compare drops the boundary day ('2026-07-01' >= '2026-07-01T…' is False)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def aio_summary(session: Session, tenant_id: int) -> dict:
    """The AIO tile (§10 M6 gate): how often Google's AI Overview answers the
    corpus, and whether the brand's domains are among its sources."""
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    brand_domains = brand.domains if brand else []
    # The AIO signal is written onto every (query, surface) classification row
    # for a query, so count each query once, not once per engine.
    by_query: dict[str, QueryClassification] = {}
    for c in session.exec(
        select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
    ).all():
        if c.google_aio_signals:  # AIO capture actually ran for this query
            by_query.setdefault(c.query_text, c)
    rows = list(by_query.values())
    measured = len(rows)
    triggered = [c for c in rows if c.google_aio_triggered]
    brand_cited = sum(
        1
        for c in triggered
        if any(
            domain_is_owned(d, brand_domains)
            for d in c.google_aio_signals.get("cited_domains", [])
        )
    )
    source_types: dict[str, int] = defaultdict(int)
    for c in rows:
        source_types[c.google_aio_source_type] += 1
    return {
        "queries_measured": measured,
        "queries_with_aio": len(triggered),
        "aio_share_pct": round(100.0 * len(triggered) / measured, 1) if measured else 0.0,
        "brand_cited_in_aio": brand_cited,
        "source_types": dict(source_types),
    }


MAX_POWER_PAGES = 30
# The consulted-but-not-cited domains list is a separate ranking; give it its
# own cap so tuning one doesn't silently move the other (§audit low).
MAX_CONSULTED_DOMAINS = 30


def citations_intel(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Citations screen (§7.1 #4): which domains AI answers cite in this
    vertical, and whether the client is among them — plus Power Pages, the
    specific URLs that feed the category's answers. Domains are trivia; pages
    are the battlefield: getting onto (or beating) one high-influence page
    moves every answer it feeds."""
    lo, hi = _date_window(start, end)
    # Count citations from the LATEST result per (query, surface) only (§audit
    # H4) — not every result across every run. Otherwise domain/Power-Page
    # counts scale with run cadence (a page cited once per daily run reads as
    # ~30) instead of reflecting citation reality.
    results_by_id = {
        r.id: r
        for r in _latest_results_by_variant(
            session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
        ).values()
        if r.id is not None
    }
    latest_ids = set(results_by_id)
    domains: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    # Per-engine source-type mix (§AEO-plan m4): where each engine draws its
    # citations from, so the earned-media playbook can be tailored per engine.
    source_types_by_engine: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for citation in session.exec(
        select(Citation).where(
            Citation.tenant_id == tenant_id,
            col(Citation.result_id).in_(list(latest_ids) or [-1]),
        ).order_by(col(Citation.id))
    ).all():
        _res = results_by_id.get(citation.result_id)
        if _res is not None:
            source_types_by_engine[str(_res.surface)][
                classify_source_type(citation.domain)
            ] += 1
        entry = domains.setdefault(
            citation.domain,
            {"domain": citation.domain, "category": citation.source_category, "count": 0,
             "surfaces": set()},
        )
        entry["count"] += 1
        if citation.source_category:
            entry["category"] = citation.source_category
        result = results_by_id.get(citation.result_id)
        if result is not None:
            entry["surfaces"].add(str(result.surface))

        page = pages.setdefault(
            citation.url,
            {"url": citation.url, "domain": citation.domain,
             "category": citation.source_category or "other",
             "citations": 0, "queries": set(), "surfaces": set()},
        )
        page["citations"] += 1
        if citation.source_category:
            page["category"] = citation.source_category
        if result is not None:
            page["queries"].add(result.query_text)
            page["surfaces"].add(str(result.surface))

    ranked = sorted(domains.values(), key=lambda d: -d["count"])
    # Influence = breadth (distinct queries the page's answers cover) first,
    # then raw citation volume.
    power = sorted(pages.values(), key=lambda p: (-len(p["queries"]), -p["citations"]))

    # On-page presence (§focus-group #2): join the crawl results so each
    # Power Page says whether the brand is actually named on it.
    presence_by_url = {
        row.url: row
        for row in session.exec(
            select(PagePresence).where(PagePresence.tenant_id == tenant_id)
        ).all()
    }

    def _with_presence(p: dict) -> dict:
        row = presence_by_url.get(p["url"])
        crawled = row if row is not None and row.status == "ok" else None
        return {
            **p,
            "queries": len(p["queries"]),
            "surfaces": sorted(p["surfaces"]),
            "on_page": crawled.brand_found if crawled else None,
            "competitors_on_page": crawled.competitors_found if crawled else [],
            "page_features": crawled.features if crawled else None,
        }

    # Consulted-but-not-cited domains (§AEO-plan M6): the engines read these on
    # the way to their answers but didn't cite them — a warm target list, since
    # they're already in the consideration set. Excludes anything already cited.
    cited_domains = set(domains)
    consulted: dict[str, dict] = {}
    for cs in session.exec(
        select(ConsultedSource).where(ConsultedSource.tenant_id == tenant_id)
    ).all():
        if cs.result_id not in latest_ids:  # §audit H4: latest results only
            continue
        src = results_by_id.get(cs.result_id)
        if cs.domain in cited_domains:
            continue
        entry = consulted.setdefault(cs.domain, {"domain": cs.domain, "count": 0, "queries": set()})
        entry["count"] += 1
        if src is not None:
            entry["queries"].add(src.query_text)
    consulted_ranked = sorted(consulted.values(), key=lambda d: -d["count"])[:MAX_CONSULTED_DOMAINS]

    return {
        "domains": [{**d, "surfaces": sorted(d["surfaces"])} for d in ranked],
        "power_pages": [_with_presence(p) for p in power[:MAX_POWER_PAGES]],
        "consulted_domains": [
            {"domain": d["domain"], "count": d["count"], "queries": len(d["queries"])}
            for d in consulted_ranked
        ],
        "source_types_by_engine": {
            surface: dict(sorted(types.items(), key=lambda kv: -kv[1]))
            for surface, types in source_types_by_engine.items()
        },
        "aio": aio_summary(session, tenant_id),
    }


def overview(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    # With an explicit range, honor it exactly; otherwise default to the
    # trailing TREND_DAYS window.
    start, end = _clean_date(start), _clean_date(end)
    cutoff = (
        start
        if start
        else (datetime.now(UTC) - timedelta(days=TREND_DAYS)).date().isoformat()
    )
    vd_conds: list[Any] = [
        VisibilityDaily.tenant_id == tenant_id, col(VisibilityDaily.date) >= cutoff
    ]
    if end:
        vd_conds.append(col(VisibilityDaily.date) <= end)
    rows = list(session.exec(select(VisibilityDaily).where(*vd_conds)).all())

    by_date: dict[str, list[VisibilityDaily]] = defaultdict(list)
    for row in rows:
        by_date[row.date].append(row)

    trend = []
    for date in sorted(by_date):
        group = by_date[date]
        competitor_values: dict[str, list[float]] = defaultdict(list)
        for row in group:
            for name, score in row.competitor_scores.items():
                competitor_values[name].append(score)
        trend.append(
            {
                "date": date,
                "brand_score": _mean([r.brand_score for r in group]),
                "competitors": {n: _mean(v) for n, v in competitor_values.items()},
            }
        )

    # Share of voice from mentions over the window (explicit range wins over
    # the trailing SOV_DAYS default).
    if start or end:
        sov_lo, sov_hi = _date_window(start, end)
    else:
        sov_lo, sov_hi = datetime.now(UTC) - timedelta(days=SOV_DAYS), None
    # Share of voice is a competitive metric — exclude branded queries (the
    # brand always appears in them, which would inflate its share).
    branded = _branded_query_texts(session, tenant_id)
    # Counted in the database: this spans every result in the window.
    sov_conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == ResultVariant.search,
        Mention.tenant_id == tenant_id,
    ]
    if branded:
        sov_conds.append(col(Result.query_text).not_in(branded))
    if sov_lo is not None:
        sov_conds.append(col(Result.created_at) >= _utc(sov_lo))
    if sov_hi is not None:
        sov_conds.append(col(Result.created_at) < _utc(sov_hi))
    mention_counts: dict[str, int] = {
        name: int(n)
        for name, n in session.exec(
            select(col(Mention.entity_name), func.count())
            .join(Result, col(Result.id) == col(Mention.result_id))
            .where(*sov_conds)
            .group_by(col(Mention.entity_name))
        ).all()
    }
    total = sum(mention_counts.values())
    share_of_voice = (
        {name: round(100.0 * count / total, 2) for name, count in mention_counts.items()}
        if total
        else {}
    )

    # Movers: last two distinct dates, brand-per-segment and competitors.
    movers: list[dict] = []
    dates = sorted(by_date)
    if len(dates) >= 2:
        prev_date, last_date = dates[-2], dates[-1]

        def segment_scores(date: str) -> dict[str, float]:
            per_segment: dict[str, list[float]] = defaultdict(list)
            for row in by_date[date]:
                per_segment[row.persona_segment or "all"].append(row.brand_score)
            return {s: _mean(v) for s, v in per_segment.items()}

        def competitor_scores(date: str) -> dict[str, float]:
            per_name: dict[str, list[float]] = defaultdict(list)
            for row in by_date[date]:
                for name, score in row.competitor_scores.items():
                    per_name[name].append(score)
            return {n: _mean(v) for n, v in per_name.items()}

        prev_seg, last_seg = segment_scores(prev_date), segment_scores(last_date)
        # Only entities measured on BOTH days: one that's missing on a day
        # isn't a 0 score, and treating it as one fakes a huge swing.
        for segment in sorted(set(prev_seg) & set(last_seg)):
            before, after = prev_seg[segment], last_seg[segment]
            movers.append(
                {
                    "label": f"Brand · {segment}",
                    "kind": "brand_segment",
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 2),
                }
            )
        prev_comp, last_comp = competitor_scores(prev_date), competitor_scores(last_date)
        for name in sorted(set(prev_comp) & set(last_comp)):
            before, after = prev_comp[name], last_comp[name]
            movers.append(
                {
                    "label": name,
                    "kind": "competitor",
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 2),
                }
            )
        movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
        movers = movers[:MAX_MOVERS]

    return {
        "brand_name": _brand_name(session, tenant_id),
        "trend": trend,
        "share_of_voice": share_of_voice,
        "movers": movers,
        "latest": (
            {"date": dates[-1], "brand_score": trend[-1]["brand_score"]} if trend else None
        ),
        "aio": aio_summary(session, tenant_id),
        "series_notes": _series_notes(session, tenant_id, [t["date"] for t in trend]),
        "mention_rate": mention_rates(session, tenant_id, start, end)["overall"],
        "alerts": alerts(session, tenant_id),
    }


# Provider-side changes that make an engine's numbers before and after a date
# different systems. A trend spanning one gets a visible note, never a silent
# "movement". (date, surface, note)
SERIES_BREAKS: list[tuple[str, SurfaceCode, str]] = [
    (
        "2026-09-27",
        SurfaceCode.perplexity_api,
        "Perplexity retired its Sonar API on Sep 27, 2026; Perplexity (API) "
        "numbers before and after come from different systems.",
    ),
    (
        "2026-10-01",
        SurfaceCode.gemini_api,
        "Gemini (API) moved from Gemini 2.5 to Gemini 3.x models on Oct 1, 2026; "
        "a model change shifts answers, so compare like with like.",
    ),
]


def _series_notes(session: Session, tenant_id: int, dates: list[str]) -> list[dict]:
    if not dates:
        return []
    lo, hi = min(dates), max(dates)
    notes = []
    for date, surface, note in SERIES_BREAKS:
        if not (lo < date <= hi):
            continue
        measured = session.exec(
            select(func.count()).select_from(Result).where(
                Result.tenant_id == tenant_id, Result.surface == surface
            )
        ).one()
        if measured:
            notes.append({"date": date, "surface": str(surface), "note": note})
    # Observed model changes (the provider started serving a different model):
    # a break in the series even when nobody announced it.
    from api.answer_shape_service import model_timeline

    seen = {(n["date"], n["surface"]) for n in notes}
    for ch in model_timeline(session, tenant_id):
        if lo < ch["since"] <= hi and (ch["since"], ch["surface"]) not in seen:
            notes.append({"date": ch["since"], "surface": ch["surface"],
                          "note": f"{ch['label']} started answering with {ch['model']}; "
                                  "compare before and after with care."})
    return sorted(notes, key=lambda n: n["date"])


def personas(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    start, end = _clean_date(start), _clean_date(end)
    cutoff = (
        start
        if start
        else (datetime.now(UTC) - timedelta(days=TREND_DAYS)).date().isoformat()
    )
    rows = [
        r
        for r in session.exec(
            select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
        ).all()
        if _date_in_range(r.date, cutoff, end)
    ]
    if not rows:
        return {"date": None, "segments": [], "trend": []}

    latest_date = max(r.date for r in rows)
    latest = [r for r in rows if r.date == latest_date]
    per_segment: dict[str, list[VisibilityDaily]] = defaultdict(list)
    for row in latest:
        per_segment[row.persona_segment or "all"].append(row)

    segments = []
    for segment in sorted(per_segment):
        group = per_segment[segment]
        competitor_values: dict[str, list[float]] = defaultdict(list)
        for row in group:
            for name, score in row.competitor_scores.items():
                competitor_values[name].append(score)
        segments.append(
            {
                "segment": segment,
                "brand_score": _mean([r.brand_score for r in group]),
                "mention_rate": _mean(
                    [float(r.extras.get("mention_rate", 0.0)) for r in group]
                ),
                "citation_rate": _mean(
                    [float(r.extras.get("citation_rate", 0.0)) for r in group]
                ),
                "result_count": sum(int(r.extras.get("result_count", 0)) for r in group),
                "competitor_scores": {n: _mean(v) for n, v in competitor_values.items()},
            }
        )

    trend_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        trend_map[(row.date, row.persona_segment or "all")].append(row.brand_score)
    trend = [
        {"date": date, "segment": segment, "brand_score": _mean(values)}
        for (date, segment), values in sorted(trend_map.items())
    ]

    return {"date": latest_date, "segments": segments, "trend": trend}


def _branded_query_texts(session: Session, tenant_id: int) -> frozenset[str]:
    """Query texts flagged branded — probes of what the model says about the
    brand. Matched by value (results snapshot query_text), so a re-import that
    changes the flag re-scopes cleanly on the next read."""
    return frozenset(
        q.text
        for q in session.exec(
            select(Query).where(
                Query.tenant_id == tenant_id,
                Query.branded == True,  # noqa: E712
            )
        ).all()
    )


def _latest_results_by_variant(
    session: Session,
    tenant_id: int,
    variant: ResultVariant,
    lo: datetime | None = None,
    hi: datetime | None = None,
    scope: str = "all",
) -> dict[tuple[str, str], Result]:
    """Newest result per (query_text, surface) for one variant, restricted to
    the [lo, hi) window when given — i.e. the state 'as of' the range's end.

    scope splits the two analysis layers (branded-query feedback):
      "all"          — every query (default; unchanged behaviour)
      "competitive"  — exclude branded queries (the visibility layer)
      "branded"      — only branded queries (the brand-knowledge layer)"""
    branded = (
        _branded_query_texts(session, tenant_id) if scope != "all" else frozenset()
    )
    if scope == "branded" and not branded:
        return {}
    # The database picks the newest id per (query, surface); only those rows
    # are loaded. Loading the whole history to keep a few dozen rows cost
    # seconds and hundreds of MB per call once a tenant has months of runs.
    conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == variant,
        Result.status == "ok",
    ]
    if lo is not None:
        conds.append(col(Result.created_at) >= _utc(lo))
    if hi is not None:
        conds.append(col(Result.created_at) < _utc(hi))
    if scope == "competitive" and branded:
        conds.append(col(Result.query_text).not_in(branded))
    if scope == "branded":
        conds.append(col(Result.query_text).in_(branded))
    newest = (
        select(func.max(Result.id))
        .where(*conds)
        .group_by(col(Result.query_text), col(Result.surface))
    )
    latest: dict[tuple[str, str], Result] = {}
    # Ordered by id, as the history scan was: callers iterate this dict and
    # some keep the first form they see, so row order must not depend on the
    # database (Postgres and SQLite return IN-subquery rows differently).
    for result in session.exec(
        select(Result).where(col(Result.id).in_(newest)).order_by(col(Result.id))
    ).all():
        latest[(result.query_text, str(result.surface))] = result
    return latest


# The "why you're absent" diagnosis, derived from the search vs training-only
# (nosearch) diff. Fixes are prescriptive and vendor-neutral.
_DIAGNOSIS = {
    "visible": {
        "label": "Visible",
        "fix": "You appear in the answer users see. Protect it: keep the cited content fresh.",
    },
    "content_gap": {
        "label": "Content gap",
        "fix": (
            "The AIs know your brand, but when they search the live web they surface "
            "competitors instead. Publish citable, up-to-date content that answers this "
            "query directly — this is a GEO/SEO content problem, not an awareness one."
        ),
    },
    "knowledge_gap": {
        "label": "Knowledge gap",
        "fix": (
            "The AIs neither recall your brand from training nor find you when they "
            "search. You need both: authoritative published content AND broader brand "
            "presence across the web so future model training picks you up."
        ),
    },
    "undetermined": {
        "label": "Absent",
        "fix": (
            "Absent from the answer. Enable an engine with a training baseline "
            "(ChatGPT, Claude, or Gemini) to diagnose whether this is a content or a "
            "knowledge gap."
        ),
    },
}


def engine_scorecard(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Cross-engine analysis: per-engine visibility, a query×engine grid of who
    appears (you / competitor / absent), and a per-query 'why you're missing'
    diagnosis from the search-vs-training diff. Pure reads — no LLM, no spend."""
    brand_name = _brand_name(session, tenant_id)
    # The competitive matrix: branded queries live on the Brand tab.
    queries = [
        q
        for q in session.exec(select(Query).where(Query.tenant_id == tenant_id)).all()
        if not q.branded
    ]

    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    nosearch = _latest_results_by_variant(
        session, tenant_id, ResultVariant.nosearch, lo, hi, scope="competitive"
    )

    # Mentions per result: brand present? which competitors?
    all_ids = [r.id for r in list(search.values()) + list(nosearch.values()) if r.id is not None]
    brand_ids: set[int] = set()
    competitors_by_result: dict[int, set[str]] = defaultdict(set)
    if all_ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(all_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            if m.entity_type == "brand":
                brand_ids.add(m.result_id)
            else:
                competitors_by_result[m.result_id].add(m.entity_name)

    # Include surfaces that produced a nosearch (training-twin) result even if
    # their search variant failed (§audit H5) — otherwise the diagnosis can't
    # see "known from training but not surfaced" and mislabels content_gap as
    # knowledge_gap/undetermined.
    surfaces = sorted({s for (_, s) in search} | {s for (_, s) in nosearch})

    # Brand-cited result ids (§AEO-plan m3): a citation to a brand-owned page,
    # distinct from a brand *mention*. Mentions and citations move
    # independently — you can be named without being linked, and vice versa.
    search_ids = [r.id for r in search.values() if r.id is not None]
    brand_cited_ids: set[int] = set()
    if search_ids:
        for c in session.exec(
            select(Citation).where(
                Citation.result_id.in_(search_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Citation.source_category == "brand",
            )
        ).all():
            brand_cited_ids.add(c.result_id)

    # Per-engine rollup.
    engines = []
    for surface in surfaces:
        measured = brand = comp = cited = 0
        comp_tally: dict[str, int] = defaultdict(int)
        for (_qtext, s), result in search.items():
            if s != surface:
                continue
            measured += 1
            if result.id in brand_ids:
                brand += 1
            if result.id in brand_cited_ids:
                cited += 1
            comps = competitors_by_result.get(result.id or -1, set())
            if comps:
                comp += 1
            for name in comps:
                comp_tally[name] += 1
        top_comp = max(comp_tally, key=lambda n: comp_tally[n]) if comp_tally else None
        brand_rate = round(100.0 * brand / measured, 1) if measured else 0.0
        citation_rate = round(100.0 * cited / measured, 1) if measured else 0.0
        engines.append({
            "surface": surface,
            "queries_measured": measured,
            "brand_present": brand,
            "brand_rate": brand_rate,
            "brand_cited": cited,
            "citation_rate": citation_rate,
            # Named but not linked: the gap the report says to watch per engine.
            "mention_citation_gap": round(brand_rate - citation_rate, 1),
            "competitor_present": comp,
            "top_competitor": top_comp,
        })

    # Per-query matrix + diagnosis.
    matrix = []
    summary: dict[str, int] = defaultdict(int)
    for query in sorted(queries, key=lambda q: (q.corpus_tag, q.text)):
        # A retired (inactive) query with nothing measured in this window
        # isn't part of the current picture.
        if not query.active and not any(
            (query.text, sf) in search or (query.text, sf) in nosearch for sf in surfaces
        ):
            continue
        cells: dict[str, dict] = {}
        brand_in_search = brand_in_nosearch = has_nosearch = False
        for surface in surfaces:
            # Check the training twin FIRST, so a surface whose search variant
            # failed but whose nosearch succeeded still informs the diagnosis
            # (§audit H5).
            ns = nosearch.get((query.text, surface))
            if ns is not None:
                has_nosearch = True
                if ns.id in brand_ids:
                    brand_in_nosearch = True
            result = search.get((query.text, surface))
            if result is None:
                continue
            comps = sorted(competitors_by_result.get(result.id or -1, set()))
            if result.id in brand_ids:
                state = "brand"
                brand_in_search = True
            elif comps:
                state = "competitor"
            else:
                state = "absent"
            cells[surface] = {"state": state, "competitors": comps}

        if brand_in_search:
            dtype = "visible"
        elif not has_nosearch:
            dtype = "undetermined"
        elif brand_in_nosearch:
            dtype = "content_gap"
        else:
            dtype = "knowledge_gap"
        summary[dtype] += 1
        matrix.append({
            "id": query.id,
            "query": query.text,
            "corpus_tag": query.corpus_tag,
            "cells": cells,
            "diagnosis": {"type": dtype, **_DIAGNOSIS[dtype]},
        })

    return {
        "brand_name": brand_name,
        "engines": engines,
        "matrix": matrix,
        "diagnosis_summary": dict(summary),
    }


def _fanout_by_query(
    search: dict[tuple[str, str], Result],
) -> dict[str, list[str]]:
    """Union of observed fan-out sub-queries per prompt across engines, deduped
    case-insensitively and excluding the prompt itself (§AEO-plan M1)."""
    out: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for (qtext, _surface), r in search.items():
        for sub in getattr(r, "fanout_queries", None) or []:
            s = str(sub).strip()
            low = s.lower()
            if not s or low == qtext.lower():
                continue
            bucket = seen.setdefault(qtext, set())
            if low in bucket:
                continue
            bucket.add(low)
            out.setdefault(qtext, []).append(s)
    return out


def fanout_report(session: Session, tenant_id: int) -> dict:
    """Query fan-out (§AEO-plan M1): the sub-queries engines actually issued on
    the way to answering each priority prompt. You no longer compete for the
    prompt — you compete shard by shard for its fan-out, so this is the map of
    the real contest surface. Populated where engines expose it (Gemini always;
    OpenAI when present)."""
    search = _latest_results_by_variant(session, tenant_id, ResultVariant.search)
    # Track, per prompt, each sub-query (deduped case-insensitively, keeping the
    # first display form) and which surfaces issued it.
    per_prompt: dict[str, dict[str, dict]] = defaultdict(dict)
    for (qtext, surface), r in search.items():
        for sub in getattr(r, "fanout_queries", None) or []:
            s = str(sub).strip()
            low = s.lower()
            if not s or low == qtext.lower():
                continue
            entry = per_prompt[qtext].setdefault(low, {"text": s, "engines": set()})
            entry["engines"].add(_surface_label(surface))

    prompts = []
    for qtext in sorted(per_prompt):
        subs = list(per_prompt[qtext].values())
        prompts.append({
            "query": qtext,
            "count": len(subs),
            "subqueries": [
                {"text": e["text"], "engines": sorted(e["engines"])}
                for e in sorted(subs, key=lambda e: (-len(e["engines"]), e["text"].lower()))
            ],
        })
    prompts.sort(key=lambda p: -p["count"])
    return {
        "brand_name": _brand_name(session, tenant_id),
        "prompts": prompts,
        "observed": bool(prompts),
    }


def fanout_scorecard(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Fan-out scorecard (§FANOUT_SCORECARD M25a + M25b): per priority prompt,
    the shards the engines actually issued, which engines issued each, and
    indicative signals from the shard TEXT (does it name the brand / a
    competitor). Per-shard PRESENCE is claimed only where the shard was
    re-probed (source 'reprobed'); every other shard is 'unresolved' and says
    why (probe_status), so partial coverage is visible, never hidden.
    Prompt-level presence comes from mentions. Competitive scope; branded
    probes live in the Brand layer. Pure reads, no spend."""
    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )

    brand_name = _brand_name(session, tenant_id)
    bp = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    brand_tokens = {t.lower() for t in ([brand_name] + (bp.aliases if bp else [])) if t}
    comp_tokens = {
        c.name: {c.name.lower(), *(a.lower() for a in c.aliases)}
        for c in session.exec(
            select(Competitor).where(Competitor.tenant_id == tenant_id)
        ).all()
    }

    # Prompt-level brand presence, from mentions on the search results.
    ids = [r.id for r in search.values() if r.id is not None]
    brand_ids: set[int] = set()
    if ids:
        for m in session.exec(
            select(Mention).where(
                Mention.result_id.in_(ids),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            brand_ids.add(m.result_id)

    # Assemble per prompt: shard -> issuing engines; reach per engine; presence.
    per_prompt: dict[str, dict] = {}
    for (qtext, surface), r in search.items():
        p = per_prompt.setdefault(
            qtext,
            {"shards": {}, "reach": defaultdict(int), "brand_in_answer": False},
        )
        if r.id in brand_ids:
            p["brand_in_answer"] = True
        label = _surface_label(surface)
        for sub in r.fanout_queries or []:
            s = str(sub).strip()
            norm = shard_norm(s)
            # Same key as the harvested FanoutShard rows, so presence joins.
            if not norm or norm == shard_norm(qtext):
                continue
            entry = p["shards"].setdefault(norm, {"text": s, "engines": set()})
            if label not in entry["engines"]:
                entry["engines"].add(label)
                p["reach"][label] += 1

    # Per-shard presence from the harvested rows: newest row per (prompt,
    # shard) in the window. Carry-forward means a fresh re-probe from an
    # earlier run is already copied onto the newest row.
    measured: dict[tuple[str, str], FanoutShard] = {}
    if per_prompt:
        for row in session.exec(
            select(FanoutShard).where(
                FanoutShard.tenant_id == tenant_id,
                FanoutShard.parent_query_text.in_(list(per_prompt)),  # pyright: ignore[reportAttributeAccessIssue]
            )
        ).all():
            if not _in_window(row.created_at, lo, hi):
                continue
            key = (row.parent_query_text, row.shard_norm)
            if key not in measured or (row.id or 0) > (measured[key].id or 0):
                measured[key] = row

    # Trend (M25c): every distinct re-probe of a shard up to the window's end,
    # oldest first. Carried rows are copies of an earlier probe, so only the
    # original measurement (probe_status 'ok') counts as a data point.
    history: dict[tuple[str, str], list[tuple[datetime, bool, int | None]]] = defaultdict(list)
    if measured:
        for row in session.exec(
            select(FanoutShard).where(
                FanoutShard.tenant_id == tenant_id,
                FanoutShard.probe_status == "ok",
                FanoutShard.parent_query_text.in_(list(per_prompt)),  # pyright: ignore[reportAttributeAccessIssue]
            )
        ).all():
            if row.probed_at is None or row.brand_present is None:
                continue
            if not _in_window(row.probed_at, None, hi):
                continue
            history[(row.parent_query_text, row.shard_norm)].append(
                (row.probed_at, row.brand_present, row.probe_result_id)
            )
        for points in history.values():
            points.sort(key=lambda pt: pt[0])

    def shard_trend(key: tuple[str, str], row: FanoutShard) -> str | None:
        """won_back | lost | steady vs the previous distinct re-probe of this
        shard; None when this is its first measurement."""
        points = history.get(key, [])
        # This row's own measurement; if it isn't in the history (probed after
        # the window's end), every point in the history is "before" it.
        idx = next(
            (
                i
                for i, pt in enumerate(points)
                if row.probe_result_id is not None and pt[2] == row.probe_result_id
            ),
            len(points),
        )
        if idx < 1:
            return None
        before, now = points[idx - 1][1], row.brand_present
        if before == now:
            return "steady"
        return "won_back" if now else "lost"

    tenant = session.get(Tenant, tenant_id)
    coverage = {"reprobed": 0, "unresolved": 0}
    trend_totals = {"won_back": 0, "lost": 0}
    prompts = []
    for qtext, p in per_prompt.items():
        shards = []
        contested = 0
        present = absent = won_back = lost = 0
        for norm, entry in p["shards"].items():
            low = entry["text"].lower()
            names_comp = sorted(
                name for name, toks in comp_tokens.items() if _names_present(low, toks)
            )
            if names_comp:
                contested += 1
            row = measured.get((qtext, norm))
            resolved = row if row is not None and row.source == "reprobed" else None
            trend = shard_trend((qtext, norm), resolved) if resolved else None
            if trend == "won_back":
                won_back += 1
            elif trend == "lost":
                lost += 1
            if resolved is not None:
                coverage["reprobed"] += 1
                if resolved.brand_present:
                    present += 1
                else:
                    absent += 1
            else:
                coverage["unresolved"] += 1
            shards.append({
                "id": row.id if row is not None else None,
                "trend": trend,
                "text": entry["text"],
                "engines": sorted(entry["engines"]),
                "names_brand": _names_present(low, brand_tokens),
                "names_competitors": names_comp,
                "brand_present": resolved.brand_present if resolved else None,
                "winners": list(resolved.winners or []) if resolved else [],
                "source": "reprobed" if resolved else "unresolved",
                "priority": resolved.priority if resolved else "",
                "probe_status": row.probe_status if row is not None else "",
                "probe_engine": _surface_label(resolved.probe_surface)
                if resolved and resolved.probe_surface else None,
                "probed_at": resolved.probed_at.isoformat()
                if resolved and resolved.probed_at else None,
            })
        shards.sort(key=lambda s: (
            PRIORITY_RANK.get(s["priority"], 3), -len(s["engines"]), s["text"].lower()
        ))
        prompts.append({
            "query": qtext,
            "shards_total": len(shards),
            "shards_present": present,
            "shards_absent": absent,
            "shards_unresolved": len(shards) - present - absent,
            "high_misses": sum(1 for s in shards if s["priority"] == "high"),
            "won_back": won_back,
            "lost": lost,
            "engines_count": len(p["reach"]),
            "reach_by_engine": dict(sorted(p["reach"].items())),
            "brand_in_answer": p["brand_in_answer"],
            "contested": contested,
            "shards": shards,
        })
        trend_totals["won_back"] += won_back
        trend_totals["lost"] += lost
    prompts.sort(key=lambda x: (-x["high_misses"], -x["shards_total"]))

    return {
        "brand_name": brand_name,
        "prompts": prompts,
        "observed": bool(prompts),
        "branded_excluded": True,
        "coverage": coverage,
        "trend": trend_totals,
        "reprobe_enabled": bool(tenant and tenant.fanout_reprobe_enabled),
    }


# Surfaces whose search variant is FORCED (tool_choice), so their search-variant
# results can't reveal natural routing — only their M2 natural probe can. Kept
# in sync with worker.jobs.A_ADAPTERS[...].forces_search.
_FORCED_SEARCH_SURFACES = {"openai_api", "perplexity_api"}
# Google's AI answer surfaces are search features: always retrieval.
_SERP_SURFACES = {"google_aio", "google_ai_mode"}
# Consumer UIs captured in a browser: no search count, so a cited source is
# the evidence that the answer searched.
_BROWSER_SURFACES = {"chatgpt_web", "perplexity_web", "copilot_web", "gemini_web"}


def routing_report(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Search-routing map (§AEO-plan M2): per engine, the share of priority
    prompts that trigger live search vs. are answered from training. Retrieval
    optimization only pays off for prompts that actually search — this is the
    'step one' diagnostic. For forced surfaces the signal comes from the
    un-forced natural probe; for the rest, from their (already un-forced)
    search variant's observed search count."""
    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    natural = _latest_results_by_variant(
        session, tenant_id, ResultVariant.natural, lo, hi, scope="competitive"
    )

    per_surface: dict[str, dict] = defaultdict(lambda: {"measured": 0, "searched": 0})
    prompts: dict[str, dict[str, bool]] = defaultdict(dict)
    for qtext, surface in set(search) | set(natural):
        if surface in _FORCED_SEARCH_SURFACES:
            src = natural.get((qtext, surface))  # only probed queries have a signal
        else:
            src = search.get((qtext, surface))
        if src is None:
            continue
        searched = (src.web_search_calls or 0) > 0
        per_surface[surface]["measured"] += 1
        per_surface[surface]["searched"] += 1 if searched else 0
        prompts[qtext][surface] = searched

    engines = [
        {
            "surface": s,
            "measured": v["measured"],
            "searched": v["searched"],
            "search_rate": _pct(v["searched"], v["measured"]),
            "from_probe": s in _FORCED_SEARCH_SURFACES,
        }
        for s, v in sorted(per_surface.items())
    ]
    rows = [
        {"query": q, "engines": dict(sorted(d.items()))}
        for q, d in sorted(prompts.items())
    ]
    return {
        "brand_name": _brand_name(session, tenant_id),
        "engines": engines,
        "prompts": rows,
        "observed": any(e["measured"] for e in engines),
    }


# Retrieve-vs-recall banding by observed search propensity in the category.
# Deliberately wide dead-band in the middle so a genuinely split engine reads
# as "mixed" rather than being forced to one pole.
_RETRIEVE_AT = 66.0
_RECALL_AT = 33.0

_MODE_PLAY = {
    "retrieve": "Publish specific, well-structured pages that answer the sub-queries "
    "these engines search.",
    "recall": "Build mentions in widely read sources (press, directories, reference "
    "sites) so future model versions learn about you.",
    "mixed": "Combine both: citable pages for searched prompts, and broad coverage "
    "for prompts answered from memory.",
}


def _brand_and_cited_ids(
    session: Session, result_ids: list[int]
) -> tuple[set[int], set[int]]:
    """(brand-mentioned ids, brand-cited ids) over a set of results, in two
    bounded queries rather than N per-result lookups."""
    brand_ids: set[int] = set()
    cited_ids: set[int] = set()
    if not result_ids:
        return brand_ids, cited_ids
    for m in session.exec(
        select(Mention).where(
            Mention.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
            Mention.entity_type == "brand",
        )
    ).all():
        brand_ids.add(m.result_id)
    for c in session.exec(
        select(Citation).where(
            Citation.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
            Citation.source_category == "brand",
        )
    ).all():
        cited_ids.add(c.result_id)
    return brand_ids, cited_ids


def engine_modes(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Reframed Overview (§AEO-plan M0): 'AI visibility' is not one number.
    Per engine, how it reaches answers in THIS category — retrieve vs recall by
    observed search propensity — and the brand's standing measured in the
    currency that matters for that mode (cited-in-live-answers for retrieval,
    named-from-memory for recall). Competitive scope only; branded probes live
    in the Brand layer. Pure reads."""
    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    natural = _latest_results_by_variant(
        session, tenant_id, ResultVariant.natural, lo, hi, scope="competitive"
    )
    nosearch = _latest_results_by_variant(
        session, tenant_id, ResultVariant.nosearch, lo, hi, scope="competitive"
    )

    all_ids = [
        r.id
        for r in (*search.values(), *natural.values(), *nosearch.values())
        if r.id is not None
    ]
    brand_ids, cited_ids = _brand_and_cited_ids(session, all_ids)
    # Captured surfaces don't report a search count. Google's AI surfaces are
    # search features by definition; a browser-captured answer searched if it
    # shows sources. Without this they'd read as "answers from memory".
    captured_ids = [
        r.id for (_q, s), r in search.items()
        if s in _BROWSER_SURFACES and r.id is not None
    ]
    sourced_ids: set[int] = set()
    if captured_ids:
        sourced_ids = set(session.exec(
            select(col(Citation.result_id))
            .where(col(Citation.result_id).in_(captured_ids))
            .distinct()
        ).all())

    def _searched(r: Result) -> bool:
        surface = str(r.surface)
        if surface in _SERP_SURFACES:
            return True
        if surface in _BROWSER_SURFACES:
            return r.id in sourced_ids
        return (r.web_search_calls or 0) > 0

    surfaces = sorted({s for (_q, s) in search} | {s for (_q, s) in natural})
    engines = []
    for surface in surfaces:
        # A forced-search surface can't reveal natural routing from its search
        # variant — read its propensity + user-visible answer from the natural
        # probe. Every other surface's search variant is already un-forced.
        forced = surface in _FORCED_SEARCH_SURFACES
        signal = natural if forced else search
        sig_rows = [r for (q, s), r in signal.items() if s == surface]
        srch_rows = [r for (q, s), r in search.items() if s == surface]
        measured = len(sig_rows)
        if not measured:
            continue
        searched = sum(1 for r in sig_rows if _searched(r))
        named = sum(1 for r in sig_rows if r.id in brand_ids)
        search_rate = _pct(searched, measured)

        if search_rate >= _RETRIEVE_AT:
            mode = "retrieve"
        elif search_rate <= _RECALL_AT:
            mode = "recall"
        else:
            mode = "mixed"

        # Fan-out breadth (retrieval engines only expose it): mean sub-queries
        # over prompts that actually searched.
        fo_seen = [
            len(r.fanout_queries)
            for r in srch_rows
            if (r.web_search_calls or 0) > 0 and r.fanout_queries
        ]
        avg_fanout = round(sum(fo_seen) / len(fo_seen), 1) if fo_seen else None

        srch_measured = len(srch_rows)
        cited = sum(1 for r in srch_rows if r.id in cited_ids)
        named_rate = _pct(named, measured)
        cited_rate = _pct(cited, srch_measured)

        if mode == "retrieve":
            standing_value, standing_unit = cited_rate, "cited"
            standing_label = "cited in live answers"
        elif mode == "recall":
            standing_value, standing_unit = named_rate, "named"
            standing_label = "named from memory"
        else:
            standing_value, standing_unit = named_rate, "named"
            standing_label = "named in answers"

        if mode == "retrieve":
            blurb = f"Searches on {round(search_rate)}% of your category prompts"
            blurb += f", splitting each into about {avg_fanout} sub-queries." if avg_fanout else "."
        elif mode == "recall":
            blurb = (
                f"Answers {round(100 - search_rate)}% of your category prompts from "
                "memory, without searching."
            )
        else:
            blurb = (
                f"Searches on {round(search_rate)}% of your category prompts and answers "
                "the rest from memory."
            )

        engines.append({
            "surface": surface,
            "label": _surface_label(surface),
            "mode": mode,
            "search_rate": search_rate,
            "avg_fanout": avg_fanout,
            "measured": measured,
            "from_probe": forced,
            "standing_value": standing_value,
            "standing_unit": standing_unit,
            "standing_label": standing_label,
            "named_rate": named_rate,
            "cited_rate": cited_rate,
            "blurb": blurb,
            "play": _MODE_PLAY[mode],
        })

    engines.sort(key=lambda e: (-e["measured"], e["surface"]))

    # Two-mode split — the honest reframe. Recall visibility is measured over
    # the training twins (what the model knows without searching); retrieval
    # visibility over the answers where it actually searched.
    # Recall = answers given WITHOUT searching: the training twins, plus
    # natural probes that chose not to search, counted once per
    # (query, surface) (a probe that searched is retrieval, not memory).
    twin_rows = [r for r in nosearch.values() if r.id is not None]
    twin_rows += [
        r
        for key, r in natural.items()
        if r.id is not None and (r.web_search_calls or 0) == 0 and key not in nosearch
    ]
    twin_named = sum(1 for r in twin_rows if r.id in brand_ids)
    searched_rows = [
        r for r in search.values() if r.id is not None and (r.web_search_calls or 0) > 0
    ]
    searched_named = sum(1 for r in searched_rows if r.id in brand_ids)
    modes = {
        "recall": {
            "visibility": _pct(twin_named, len(twin_rows)),
            "answers": len(twin_rows),
        },
        "retrieval": {
            "visibility": _pct(searched_named, len(searched_rows)),
            "answers": len(searched_rows),
        },
    }

    # Composite — demoted to a blended roll-up, not the headline. Latest daily
    # brand score, the same figure the trend chart lands on.
    start, end = _clean_date(start), _clean_date(end)
    latest_daily = None
    daily = [
        r for r in session.exec(
            select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
        ).all()
        if _date_in_range(r.date, start, end)
    ]
    if daily:
        last_date = max(r.date for r in daily)
        scores = [r.brand_score for r in daily if r.date == last_date]
        if scores:
            latest_daily = {"score": round(_mean(scores), 1), "date": last_date}

    return {
        "brand_name": _brand_name(session, tenant_id),
        "engines": engines,
        "modes": modes,
        "composite": latest_daily,
        "observed": bool(engines),
    }


def accuracy_report(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Factual-accuracy findings over the latest answers (§AEO-plan M4): where
    engines state something the fact sheet says is wrong, grouped by fact with
    the engines that repeat it. Degrades to 'no facts on file' when the tenant
    hasn't entered any."""
    facts_on_file = len(session.exec(
        select(BrandFact).where(
            BrandFact.tenant_id == tenant_id, BrandFact.active == True  # noqa: E712
        )
    ).all())

    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(session, tenant_id, ResultVariant.search, lo, hi)
    surface_by_id = {r.id: str(r.surface) for r in search.values() if r.id is not None}
    ids = list(surface_by_id)
    grouped: dict[tuple, dict] = {}
    if ids:
        for fnd in session.exec(
            select(AccuracyFinding).where(
                AccuracyFinding.tenant_id == tenant_id,
                AccuracyFinding.result_id.in_(ids),  # pyright: ignore[reportAttributeAccessIssue]
            )
        ).all():
            key = (fnd.fact_id, fnd.stated)
            g = grouped.setdefault(key, {
                "fact_id": fnd.fact_id,  # to close the loop: generate corrective content
                "subject": fnd.subject, "category": fnd.category, "severity": fnd.severity,
                "expected": fnd.expected, "stated": fnd.stated, "detail": fnd.detail,
                "snippet": fnd.snippet, "engines": set(),
            })
            surface = surface_by_id.get(fnd.result_id)
            if surface:
                g["engines"].add(_surface_label(surface))

    errors = sorted(
        (
            {**{k: v for k, v in g.items() if k != "engines"},
             "engines": sorted(g["engines"])}
            for g in grouped.values()
        ),
        key=lambda e: (-len(e["engines"]), e["subject"]),
    )
    return {
        "brand_name": _brand_name(session, tenant_id),
        "facts_on_file": facts_on_file,
        "measured": len(ids),
        "error_count": len(errors),
        "errors": errors,
    }


def brand_report(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Brand-knowledge layer (branded-query feedback): what the models say when
    asked directly about the brand. Branded queries are excluded from the
    competitive visibility metrics precisely because the brand nearly always
    appears — so here we report presence (a red flag if it DROPS), the framing
    (sentiment), the exact snippet the model returned, and the accuracy issues.
    This is the source of truth for what the model knows about the brand."""
    lo, hi = _date_window(start, end)
    branded = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="branded"
    )
    result_meta = {r.id: (qtext, surface) for (qtext, surface), r in branded.items()
                   if r.id is not None}
    result_ids = list(result_meta)

    brand_mention: dict[int, Mention] = {}
    if result_ids:
        for m in session.exec(
            select(Mention).where(
                Mention.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            # keep the best-ranked brand mention per result
            cur = brand_mention.get(m.result_id)
            if cur is None or (m.rank or 999) < (cur.rank or 999):
                brand_mention[m.result_id] = m

    findings_by_result: dict[int, list[AccuracyFinding]] = defaultdict(list)
    if result_ids:
        for f in session.exec(
            select(AccuracyFinding).where(
                AccuracyFinding.tenant_id == tenant_id,
                AccuracyFinding.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
            )
        ).all():
            findings_by_result[f.result_id].append(f)

    sentiment_mix: dict[str, int] = defaultdict(int)
    present_cells = 0
    per_query: dict[str, dict] = {}
    for rid, (qtext, surface) in result_meta.items():
        q = per_query.setdefault(qtext, {"query": qtext, "surfaces": [], "accuracy": []})
        m = brand_mention.get(rid)
        present = m is not None
        if m is not None:
            present_cells += 1
            sentiment_mix[m.sentiment or "neutral"] += 1
        q["surfaces"].append({
            "surface": _surface_label(surface),
            "present": present,
            "sentiment": m.sentiment if m else None,
            "snippet": (m.context_snippet if m else "")[:240],
        })
        for f in findings_by_result.get(rid, []):
            q["accuracy"].append({
                "subject": f.subject, "stated": f.stated, "expected": f.expected,
                "detail": f.detail, "engine": _surface_label(surface),
            })

    queries = sorted(per_query.values(), key=lambda x: x["query"])
    for q in queries:
        q["surfaces"].sort(key=lambda s: s["surface"])
    total_cells = len(result_ids)
    return {
        "brand_name": _brand_name(session, tenant_id),
        "queries_tracked": len(queries),
        "measured": total_cells,
        "presence_rate": _pct(present_cells, total_cells),
        "sentiment": dict(sentiment_mix),
        "accuracy_issues": sum(len(v) for v in findings_by_result.values()),
        "queries": queries,
        "observed": total_cells > 0,
    }


def whitespace_report(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Out-of-list competitors (§step 4 — the whitespace slide): products the AI
    surfaces that the tenant doesn't track, ranked by how often they appear,
    with the persona segments and engines that surfaced them. 'Here's who the AI
    recommends, and none of them is on your list.' Reads the latest search
    results in the window so it tracks current state, not all-time."""
    lo, hi = _date_window(start, end)
    latest = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    result_meta = {
        r.id: (r.persona_segment or "generic", str(r.surface))
        for r in latest.values()
        if r.id is not None
    }
    latest_ids = set(result_meta)

    agg: dict[str, dict] = {}
    if latest_ids:
        for um in session.exec(
            select(UntrackedMention).where(UntrackedMention.tenant_id == tenant_id)
        ).all():
            if um.result_id not in latest_ids:
                continue
            entry = agg.setdefault(
                um.entity_name,
                {"name": um.entity_name, "count": 0, "segments": set(), "surfaces": set()},
            )
            entry["count"] += 1
            seg, surface = result_meta[um.result_id]
            entry["segments"].add(seg)
            entry["surfaces"].add(surface)

    entities = [
        {
            "name": e["name"],
            "count": e["count"],
            "segments": sorted(e["segments"]),
            "engines": sorted(_surface_label(s) for s in e["surfaces"]),
        }
        for e in sorted(agg.values(), key=lambda e: (-e["count"], e["name"]))
    ]
    return {
        "brand_name": _brand_name(session, tenant_id),
        "measured": len(latest_ids),
        "entity_count": len(entities),
        "entities": entities,
        "observed": bool(entities),
    }


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


STABILITY_RUNS = 8


MENTION_WINDOW_DAYS = 28


def mention_rates(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Headline measurement: how often AI answers name the brand, pooled over
    a window, per engine and overall — each with a 95% range — plus whether
    the second half of the window differs from the first by more than noise.

    Every ok search answer to a competitive (non-branded) query counts, across
    all runs in the window: repeated runs are samples, not duplicates. Counted
    in the database, so it stays fast at any history size."""
    lo, hi = _date_window(start, end)
    now = datetime.now(UTC)
    hi_eff = _utc(hi) if hi is not None else now
    lo_eff = _utc(lo) if lo is not None else hi_eff - timedelta(days=MENTION_WINDOW_DAYS)
    mid = lo_eff + (hi_eff - lo_eff) / 2
    branded = _branded_query_texts(session, tenant_id)
    conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == ResultVariant.search,
        Result.status == ResultStatus.ok,
        col(Result.created_at) >= lo_eff,
        col(Result.created_at) < hi_eff,
    ]
    if branded:
        conds.append(col(Result.query_text).not_in(branded))
    brand_hits = (
        select(col(Mention.result_id))
        .where(Mention.tenant_id == tenant_id, Mention.entity_type == "brand")
        .distinct()
        .subquery()
    )
    second_half = case((col(Result.created_at) >= mid, 1), else_=0)
    rows = session.exec(
        select(
            col(Result.surface), second_half,
            func.count(col(Result.id)), func.count(brand_hits.c.result_id),
        )
        .outerjoin(brand_hits, brand_hits.c.result_id == col(Result.id))
        .where(*conds)
        .group_by(col(Result.surface), second_half)
    ).all()
    # Keyed by plain string: the dialect may return the enum or its value.
    prompts: dict[str, int] = {
        str(surface): int(n)
        for surface, n in session.exec(
            select(col(Result.surface), func.count(func.distinct(col(Result.query_text))))
            .where(*conds)
            .group_by(col(Result.surface))
        ).all()
    }
    # counts[surface] = [k_first, n_first, k_second, n_second]
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for surface, half, n, k in rows:
        c = counts[str(surface)]
        if half:
            c[2] += int(k)
            c[3] += int(n)
        else:
            c[0] += int(k)
            c[1] += int(n)

    def _entry(c: list[int]) -> dict:
        return {
            **rate_summary(c[0] + c[2], c[1] + c[3]),
            "change": change_verdict(c[0], c[1], c[2], c[3]),
        }

    total = [sum(c[i] for c in counts.values()) for i in range(4)]
    engines = sorted(
        (
            {
                "surface": surface,
                "label": _surface_label(surface),
                "prompts": prompts.get(surface, 0),
                **_entry(c),
            }
            for surface, c in counts.items()
        ),
        key=lambda e: -int(e["answers"]),
    )
    return {
        "window": {"start": lo_eff.date().isoformat(), "end": hi_eff.date().isoformat(),
                   "split": mid.date().isoformat()},
        "overall": {
            "prompts": int(session.exec(
                select(func.count(func.distinct(col(Result.query_text)))).where(*conds)
            ).one() or 0),
            **_entry(total),
        },
        "engines": engines,
    }


def alerts(session: Session, tenant_id: int) -> list[dict]:
    """What changed that someone should act on, most urgent first. Each item:
    {severity: high|medium|good, kind, text}. Only REAL changes: visibility
    moves must clear the noise test; citations lost are compared run to run.
    Pure reads; feeds the Overview block and the run email."""
    out: list[dict] = []
    rates = mention_rates(session, tenant_id)
    for e in [{**rates["overall"], "label": "Overall"}, *rates["engines"]]:
        ch = e["change"]
        if ch["verdict"] == "down":
            out.append({
                "severity": "high", "kind": "visibility_drop",
                "text": f"{e['label']}: mention rate fell {abs(ch['delta'])}pt to "
                        f"{e['rate']}% ({e['low']}–{e['high']}%). A real change, not noise.",
            })
        elif ch["verdict"] == "up":
            out.append({
                "severity": "good", "kind": "visibility_gain",
                "text": f"{e['label']}: mention rate rose {ch['delta']}pt to {e['rate']}% "
                        f"({e['low']}–{e['high']}%).",
            })
    lost = _lost_citations(session, tenant_id)
    if lost.get("ready"):
        for item in lost.get("lost", [])[:3]:
            n = len(item["queries"])
            out.append({
                "severity": "medium", "kind": "citation_lost",
                "text": f"Lost a citation: {item['url']} is no longer cited for {n} "
                        f"question{'s' if n != 1 else ''}. Refresh its dates, stats and "
                        "examples.",
            })
    latest_run = session.exec(
        select(func.max(Result.run_id)).where(Result.tenant_id == tenant_id)
    ).one()
    if latest_run is not None:
        wrong = session.exec(
            select(col(AccuracyFinding.subject), func.count())
            .join(Result, col(Result.id) == col(AccuracyFinding.result_id))
            .where(AccuracyFinding.tenant_id == tenant_id, Result.run_id == latest_run)
            .group_by(col(AccuracyFinding.subject))
        ).all()
        for subject, n in sorted(wrong, key=lambda r: -int(r[1]))[:3]:
            out.append({
                "severity": "high", "kind": "accuracy",
                "text": f"AI answers state something wrong about {subject or 'your brand'} "
                        f"({n} answer{'s' if n != 1 else ''} in the latest run).",
            })
    order = {"high": 0, "medium": 1, "good": 2}
    out.sort(key=lambda a: order.get(a["severity"], 3))
    return out


def kpi_scorecard(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """The KPIs an AEO panel converged on (§panel): a prominence-weighted
    Answer Share (north-star), plus prominence, competitive head-to-head,
    sentiment/framing, and run-over-run stability. Pure reads over the
    mention/rank/sentiment data already captured — no LLM, no run spend."""
    brand_name = _brand_name(session, tenant_id)
    lo, hi = _date_window(start, end)
    # Competitive scope: branded queries (the brand always appears) don't count
    # toward the visibility KPIs — they're the Brand-knowledge layer.
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    results = list(search.values())
    result_ids = [r.id for r in results if r.id is not None]

    mentions_by_result: dict[int, list[Mention]] = defaultdict(list)
    if result_ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            mentions_by_result[m.result_id].append(m)

    measured = len(results)
    present = leads = 0
    brand_ranks: list[int] = []
    pos_buckets = {"leads": 0, "second": 0, "third_plus": 0}
    weight_total = 0.0
    weight_by_entity: dict[str, float] = defaultdict(float)
    sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
    examples: dict[str, list[dict]] = {"positive": [], "negative": []}
    comp_stats: dict[str, dict] = defaultdict(lambda: {"shared": 0, "wins": 0})

    for r in results:
        ms = mentions_by_result.get(r.id or -1, [])
        for m in ms:
            # rank is 1-based (detector assigns 1..n); guard ≥1 explicitly so a
            # stray 0 contributes no weight rather than dividing by zero.
            weight = 1.0 / m.rank if m.rank >= 1 else 0.0
            weight_total += weight
            name = brand_name if m.entity_type == "brand" else m.entity_name
            weight_by_entity[name] += weight

        brand_ms = [m for m in ms if m.entity_type == "brand"]
        if not brand_ms:
            continue
        bm = min(brand_ms, key=lambda m: m.rank or 999)
        present += 1
        brand_ranks.append(bm.rank)
        if bm.rank == 1:
            leads += 1
            pos_buckets["leads"] += 1
        elif bm.rank == 2:
            pos_buckets["second"] += 1
        else:
            pos_buckets["third_plus"] += 1
        sentiment_counts[bm.sentiment] = sentiment_counts.get(bm.sentiment, 0) + 1
        if bm.sentiment in examples and len(examples[bm.sentiment]) < 3 and bm.context_snippet:
            examples[bm.sentiment].append(
                {"query": r.query_text, "surface": str(r.surface), "snippet": bm.context_snippet}
            )
        # Head-to-head: among results where the brand appears, who leads whom.
        b_rank = bm.rank
        for m in ms:
            if m.entity_type != "brand":
                cs = comp_stats[m.entity_name]
                cs["shared"] += 1
                if b_rank < (m.rank or 999):
                    cs["wins"] += 1

    answer_share = _pct(weight_by_entity.get(brand_name, 0.0), weight_total)
    share_breakdown = sorted(
        ({"name": n, "share": _pct(w, weight_total)} for n, w in weight_by_entity.items()),
        key=lambda x: -float(x["share"]),
    )
    head_to_head = sorted(
        (
            {
                "competitor": name,
                "shared": s["shared"],
                "wins": s["wins"],
                "win_rate": _pct(s["wins"], s["shared"]),
            }
            for name, s in comp_stats.items()
        ),
        key=lambda x: -int(x["shared"]),
    )

    # Stability: brand presence rate across the last few runs (in-window).
    # Competitive queries only, matching presence_rate on the same screen
    # (branded queries name the brand almost always and would inflate it).
    branded_texts = _branded_query_texts(session, tenant_id)
    st_conds: list[Any] = [
        Result.tenant_id == tenant_id, Result.variant == ResultVariant.search,
        Result.status == "ok",
    ]
    if lo is not None:
        st_conds.append(col(Result.created_at) >= _utc(lo))
    if hi is not None:
        st_conds.append(col(Result.created_at) < _utc(hi))
    if branded_texts:
        st_conds.append(col(Result.query_text).not_in(branded_texts))
    # Only the last STABILITY_RUNS runs are used; load just those.
    recent_run_ids = session.exec(
        select(col(Result.run_id)).where(*st_conds)
        .group_by(col(Result.run_id)).order_by(col(Result.run_id).desc())
        .limit(STABILITY_RUNS)
    ).all()
    by_run: dict[int, list[Result]] = defaultdict(list)
    if recent_run_ids:
        for r in session.exec(
            select(Result).where(*st_conds, col(Result.run_id).in_(recent_run_ids))
        ).all():
            by_run[r.run_id].append(r)
    recent_runs = sorted(by_run)[-STABILITY_RUNS:]
    run_ids_flat = [x.id for rid in recent_runs for x in by_run[rid] if x.id is not None]
    brand_result_ids: set[int] = set()
    if run_ids_flat:
        for m in session.exec(
            select(Mention).where(
                Mention.result_id.in_(run_ids_flat),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            brand_result_ids.add(m.result_id)
    series = [
        {
            "run_id": rid,
            "presence_rate": _pct(
                sum(1 for x in by_run[rid] if x.id in brand_result_ids), len(by_run[rid])
            ),
        }
        for rid in recent_runs
    ]
    rates = [s["presence_rate"] for s in series]
    swing = round(max(rates) - min(rates), 1) if rates else 0.0
    if len(series) < 2:
        stability_label = "Not enough history"
    elif swing < 10:
        stability_label = "Stable"
    elif swing < 25:
        stability_label = "Some volatility"
    else:
        stability_label = "Volatile"

    return {
        "brand_name": brand_name,
        "mention_rates": mention_rates(session, tenant_id, start, end),
        "answer_share": answer_share,
        "share_breakdown": share_breakdown,
        "prominence": {
            "measured": measured,
            "present": present,
            "presence_rate": _pct(present, measured),
            "lead_rate": _pct(leads, present),
            "avg_rank": round(sum(brand_ranks) / len(brand_ranks), 2) if brand_ranks else None,
            "position_distribution": pos_buckets,
        },
        "sentiment": {
            "counts": sentiment_counts,
            "examples": examples,
        },
        "head_to_head": head_to_head,
        "stability": {
            "series": series,
            "mean": round(sum(rates) / len(rates), 1) if rates else 0.0,
            "swing": swing,
            "stdev": round(_stdev(rates), 1),
            "label": stability_label,
        },
    }


def outcome(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """The Outcome view (panel #6): AI-referred sessions + conversions from GA4,
    overlaid on the brand-visibility trend. Answers 'did visibility move the
    business'. Empty until a GA4 property is connected and the nightly pull
    runs."""
    start, end = _clean_date(start), _clean_date(end)
    tenant = session.get(Tenant, tenant_id)
    all_referrals = list(
        session.exec(select(AiReferralDaily).where(AiReferralDaily.tenant_id == tenant_id)).all()
    )
    referrals = [r for r in all_referrals if _date_in_range(r.date, start, end)]

    def _zero() -> dict[str, int]:
        return {"sessions": 0, "conversions": 0}

    by_date: dict[str, dict[str, int]] = defaultdict(_zero)
    engine_totals: dict[str, dict[str, int]] = defaultdict(_zero)
    for r in referrals:
        by_date[r.date]["sessions"] += r.sessions
        by_date[r.date]["conversions"] += r.conversions
        engine_totals[r.engine]["sessions"] += r.sessions
        engine_totals[r.engine]["conversions"] += r.conversions

    # Brand-visibility score per date (mean over the day's rollup rows).
    vis_by_date: dict[str, list[float]] = defaultdict(list)
    for v in session.exec(
        select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
    ).all():
        if _date_in_range(v.date, start, end):
            vis_by_date[v.date].append(v.brand_score)

    dates = sorted(set(by_date) | set(vis_by_date))
    series = [
        {
            "date": d,
            "sessions": by_date[d]["sessions"] if d in by_date else 0,
            "conversions": by_date[d]["conversions"] if d in by_date else 0,
            "brand_score": _mean(vis_by_date[d]) if d in vis_by_date else None,
        }
        for d in dates
    ]
    totals = {
        "sessions": sum(e["sessions"] for e in engine_totals.values()),
        "conversions": sum(e["conversions"] for e in engine_totals.values()),
    }
    return {
        "brand_name": _brand_name(session, tenant_id),
        "connected": bool(tenant and tenant.ga4_property_id),
        # Reflect the SELECTED window, not all-time: series/totals are windowed,
        # so an all-time flag would suppress the empty state for a range that
        # happens to contain no referrals, leaving a blank chart (§audit low).
        "has_data": bool(referrals),
        "series": series,
        "engine_totals": [
            {"engine": e, **vals}
            for e, vals in sorted(engine_totals.items(), key=lambda kv: -kv[1]["sessions"])
        ],
        "totals": totals,
    }


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def interventions_report(session: Session, tenant_id: int) -> dict:
    """The fix→proof loop (§CMO #1): for every shipped intervention, brand
    presence on its query before vs after the ship date — with a same-window
    control (all queries with no intervention) so the client can see whether
    the lift beats the tide. Honest 'awaiting post-ship runs' state until a
    run lands after the ship date."""
    ledger = list(
        session.exec(
            select(Intervention)
            .where(Intervention.tenant_id == tenant_id)
            .order_by(Intervention.shipped_at.desc())  # pyright: ignore[reportAttributeAccessIssue]
        ).all()
    )

    if not ledger:
        return {"interventions": [], "aggregate": None}

    result_conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == ResultVariant.search,
        Result.status == "ok",
    ]
    rows = [
        (query_text, str(surface), _as_utc(created_at), rid)
        for query_text, surface, created_at, rid in session.exec(
            select(
                col(Result.query_text), col(Result.surface),
                col(Result.created_at), col(Result.id),
            ).where(*result_conds)
        ).all()
        if rid is not None
    ]
    # Joined in the database rather than an IN list of every result id.
    brand_ids: set[int] = set(
        session.exec(
            select(col(Mention.result_id))
            .join(Result, col(Result.id) == col(Mention.result_id))
            .where(*result_conds, Mention.entity_type == "brand")
        ).all()
    )

    treated_queries = {i.query_text for i in ledger}

    # Bucket results by query once so rate() scans only the queries it's asked
    # about instead of the whole result history on every call (§audit low): the
    # per-item treated + control rate() calls otherwise made it O(ledger × rows).
    rows_by_query: dict[str, list[tuple[str, str, datetime, int]]] = defaultdict(list)
    for row in rows:
        rows_by_query[row[0]].append(row)

    def rate(queries: set[str], *, before: datetime | None = None,
             after: datetime | None = None) -> tuple[int, int]:
        present = total = 0
        for q in queries:
            for _q, _s, created, rid in rows_by_query.get(q, ()):
                if before is not None and created >= before:
                    continue
                if after is not None and created < after:
                    continue
                total += 1
                if rid in brand_ids:
                    present += 1
        return present, total

    def pct(present: int, total: int) -> float | None:
        return round(100.0 * present / total, 1) if total else None

    out = []
    deltas: list[float] = []
    control_deltas: list[float] = []
    # Branded queries name the brand almost always; as controls they'd damp
    # the untouched-query baseline toward zero and flatter the lift.
    control_queries = (
        {q for (q, _s, _c, _r) in rows} - treated_queries - _branded_query_texts(session, tenant_id)
    )
    for item in ledger:
        shipped = _as_utc(item.shipped_at)
        b_present, b_total = rate({item.query_text}, before=shipped)
        a_present, a_total = rate({item.query_text}, after=shipped)
        before_rate, after_rate = pct(b_present, b_total), pct(a_present, a_total)

        # Engines where the brand was absent before and present after.
        item_rows = rows_by_query.get(item.query_text, ())
        engines_before = {s for (_q, s, c, rid) in item_rows
                          if c < shipped and rid in brand_ids}
        engines_after = {s for (_q, s, c, rid) in item_rows
                         if c >= shipped and rid in brand_ids}
        newly_visible = sorted(engines_after - engines_before)

        delta = None
        control_delta = None
        if before_rate is not None and after_rate is not None:
            delta = round(after_rate - before_rate, 1)
            deltas.append(delta)
            cb = pct(*rate(control_queries, before=shipped))
            ca = pct(*rate(control_queries, after=shipped))
            if cb is not None and ca is not None:
                control_delta = round(ca - cb, 1)
                control_deltas.append(control_delta)

        out.append({
            "id": item.id,
            "query": item.query_text,
            "description": item.description,
            "url": item.url,
            "shipped_at": shipped.date().isoformat(),
            "created_by": item.created_by,
            "before_rate": before_rate,
            "after_rate": after_rate,
            "delta": delta,
            "control_delta": control_delta,
            "newly_visible": newly_visible,
            "awaiting": a_total == 0,
        })

    aggregate = None
    if deltas:
        aggregate = {
            "measured": len(deltas),
            "avg_delta": round(sum(deltas) / len(deltas), 1),
            "avg_control_delta": (
                round(sum(control_deltas) / len(control_deltas), 1) if control_deltas else None
            ),
        }
    return {"interventions": out, "aggregate": aggregate}


def _owned_domains(session: Session, tenant_id: int) -> list[str]:
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    return brand.domains if brand else []


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
    branded = _branded_query_texts(session, tenant_id)
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


def _surface_label(surface: str) -> str:
    """Server-side surface label mirror (the client also labels); keeps briefs
    readable if rendered outside the app (e.g. an exported report)."""
    labels = {
        "openai_api": "ChatGPT", "perplexity_api": "Perplexity", "claude_api": "Claude",
        "gemini_api": "Gemini", "chatgpt_web": "ChatGPT (web)",
        "perplexity_web": "Perplexity (web)",
        "gemini_web": "Gemini (web)", "copilot_web": "Microsoft Copilot",
        "google_aio": "Google AI Overviews",
        "google_ai_mode": "Google AI Mode",
    }
    return labels.get(surface, surface)


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


def queries_intel(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    queries = list(session.exec(select(Query).where(Query.tenant_id == tenant_id)).all())
    classifications = {
        (c.query_text, str(c.surface)): c
        for c in session.exec(
            select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
        ).all()
    }

    # Latest search-variant result per (query_text, surface), in-window.
    lo, hi = _date_window(start, end)
    # Prefer the newest SUCCESSFUL answer per (query, surface): a failed or
    # blocked retry must not hide the last good one (it would read as "brand
    # not mentioned"). Fall back to the newest attempt when none succeeded.
    # Both picks happen in the database; only the chosen rows are loaded.
    conds: list[Any] = [Result.tenant_id == tenant_id, Result.variant == ResultVariant.search]
    if lo is not None:
        conds.append(col(Result.created_at) >= _utc(lo))
    if hi is not None:
        conds.append(col(Result.created_at) < _utc(hi))
    key_cols = (col(Result.query_text), col(Result.surface))
    newest_ok = {
        (qt, str(sf)): rid
        for qt, sf, rid in session.exec(
            select(*key_cols, func.max(Result.id))
            .where(*conds, Result.status == ResultStatus.ok)
            .group_by(*key_cols)
        ).all()
    }
    newest_any = {
        (qt, str(sf)): rid
        for qt, sf, rid in session.exec(
            select(*key_cols, func.max(Result.id)).where(*conds).group_by(*key_cols)
        ).all()
    }
    chosen = {key: newest_ok.get(key, rid) for key, rid in newest_any.items()}
    by_id = {
        r.id: r
        for r in session.exec(
            select(Result).where(col(Result.id).in_(list(chosen.values()) or [-1]))
        ).all()
    }
    latest_results: dict[tuple[str, str], Result] = {
        key: by_id[rid]
        for key, rid in sorted(chosen.items(), key=lambda kv: kv[1] or 0)
        if rid in by_id
    }

    result_ids = [r.id for r in latest_results.values() if r.id is not None]
    brand_mentioned_ids: set[int] = set()
    if result_ids:
        for mention in session.exec(
            select(Mention).where(
                Mention.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            brand_mentioned_ids.add(mention.result_id)

    out = []
    for query in sorted(queries, key=lambda q: (q.corpus_tag, q.text)):
        surfaces: dict[str, dict] = {}
        for (query_text, surface), result in latest_results.items():
            if query_text != query.text:
                continue
            surfaces[surface] = {
                "result_id": result.id,
                "run_id": result.run_id,
                "status": result.status,
                "mode": str(result.mode),
                "brand_mentioned": result.id in brand_mentioned_ids,
            }
        # A query can be classified per surface; pick a DETERMINISTIC one (the
        # lowest surface code) rather than whichever the dict happens to yield
        # first, so the reported likelihood doesn't drift between deploys.
        classification = None
        matches = sorted(
            ((surface, c) for (qt, surface), c in classifications.items() if qt == query.text),
            key=lambda pair: pair[0],
        )
        if matches:
            surface, c = matches[0]
            classification = {
                "surface": surface,
                "web_search_likelihood": c.web_search_likelihood,
                "signals": c.signals,
                "classifier_version": c.classifier_version,
            }
        out.append(
            {
                "id": query.id,
                "text": query.text,
                "corpus_tag": query.corpus_tag,
                "active": query.active,
                "branded": query.branded,
                "classification": classification,
                "latest_results": surfaces,
            }
        )
    return {"queries": out}
