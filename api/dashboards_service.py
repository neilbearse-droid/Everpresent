"""Read-side aggregation for the client dashboards (§7.1 Overview, Personas,
Queries). Pure Postgres reads over the processed rollups — no LLM, no
provider calls."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from api.models import (
    AiReferralDaily,
    BrandProfile,
    Citation,
    Mention,
    Query,
    QueryClassification,
    Result,
    ResultVariant,
    Tenant,
    VisibilityDaily,
)
from engine.processing.citations import domain_is_owned

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


def aio_summary(session: Session, tenant_id: int) -> dict:
    """The AIO tile (§10 M6 gate): how often Google's AI Overview answers the
    corpus, and whether the brand's domains are among its sources."""
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    brand_domains = brand.domains if brand else []
    rows = [
        c
        for c in session.exec(
            select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
        ).all()
        if c.google_aio_signals  # AIO capture actually ran for this query
    ]
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


def citations_intel(session: Session, tenant_id: int) -> dict:
    """Citations screen (§7.1 #4): which domains AI answers cite in this
    vertical, and whether the client is among them."""
    results_by_id = {
        r.id: r
        for r in session.exec(select(Result).where(Result.tenant_id == tenant_id)).all()
        if r.id is not None
    }
    domains: dict[str, dict] = {}
    for citation in session.exec(
        select(Citation).where(Citation.tenant_id == tenant_id)
    ).all():
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
    ranked = sorted(domains.values(), key=lambda d: -d["count"])
    return {
        "domains": [{**d, "surfaces": sorted(d["surfaces"])} for d in ranked],
        "aio": aio_summary(session, tenant_id),
    }


def overview(session: Session, tenant_id: int) -> dict:
    cutoff = (datetime.now(UTC) - timedelta(days=TREND_DAYS)).date().isoformat()
    rows = [
        r
        for r in session.exec(
            select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
        ).all()
        if r.date >= cutoff
    ]

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

    # Share of voice from mentions over the window.
    sov_cutoff = datetime.now(UTC) - timedelta(days=SOV_DAYS)
    recent_result_ids = {
        r.id
        for r in session.exec(select(Result).where(Result.tenant_id == tenant_id)).all()
        if r.id is not None
        and r.variant == ResultVariant.search
        and (r.created_at.replace(tzinfo=UTC) if r.created_at.tzinfo is None else r.created_at)
        >= sov_cutoff
    }
    mention_counts: dict[str, int] = defaultdict(int)
    for mention in session.exec(
        select(Mention).where(Mention.tenant_id == tenant_id)
    ).all():
        if mention.result_id in recent_result_ids:
            mention_counts[mention.entity_name] += 1
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
        for segment in sorted(set(prev_seg) | set(last_seg)):
            before, after = prev_seg.get(segment, 0.0), last_seg.get(segment, 0.0)
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
        for name in sorted(set(prev_comp) | set(last_comp)):
            before, after = prev_comp.get(name, 0.0), last_comp.get(name, 0.0)
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
    }


def personas(session: Session, tenant_id: int) -> dict:
    cutoff = (datetime.now(UTC) - timedelta(days=TREND_DAYS)).date().isoformat()
    rows = [
        r
        for r in session.exec(
            select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
        ).all()
        if r.date >= cutoff
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


def _latest_results_by_variant(
    session: Session, tenant_id: int, variant: ResultVariant
) -> dict[tuple[str, str], Result]:
    """Newest result per (query_text, surface) for one variant."""
    latest: dict[tuple[str, str], Result] = {}
    for result in session.exec(
        select(Result).where(
            Result.tenant_id == tenant_id,
            Result.variant == variant,
            Result.status == "ok",
        )
    ).all():
        key = (result.query_text, str(result.surface))
        if key not in latest or (result.id or 0) > (latest[key].id or 0):
            latest[key] = result
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


def engine_scorecard(session: Session, tenant_id: int) -> dict:
    """Cross-engine analysis: per-engine visibility, a query×engine grid of who
    appears (you / competitor / absent), and a per-query 'why you're missing'
    diagnosis from the search-vs-training diff. Pure reads — no LLM, no spend."""
    brand_name = _brand_name(session, tenant_id)
    queries = list(session.exec(select(Query).where(Query.tenant_id == tenant_id)).all())

    search = _latest_results_by_variant(session, tenant_id, ResultVariant.search)
    nosearch = _latest_results_by_variant(session, tenant_id, ResultVariant.nosearch)

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

    surfaces = sorted({s for (_, s) in search})

    # Per-engine rollup.
    engines = []
    for surface in surfaces:
        measured = brand = comp = 0
        comp_tally: dict[str, int] = defaultdict(int)
        for (_qtext, s), result in search.items():
            if s != surface:
                continue
            measured += 1
            if result.id in brand_ids:
                brand += 1
            comps = competitors_by_result.get(result.id or -1, set())
            if comps:
                comp += 1
            for name in comps:
                comp_tally[name] += 1
        top_comp = max(comp_tally, key=lambda n: comp_tally[n]) if comp_tally else None
        engines.append({
            "surface": surface,
            "queries_measured": measured,
            "brand_present": brand,
            "brand_rate": round(100.0 * brand / measured, 1) if measured else 0.0,
            "competitor_present": comp,
            "top_competitor": top_comp,
        })

    # Per-query matrix + diagnosis.
    matrix = []
    summary: dict[str, int] = defaultdict(int)
    for query in sorted(queries, key=lambda q: (q.corpus_tag, q.text)):
        cells: dict[str, dict] = {}
        brand_in_search = brand_in_nosearch = has_nosearch = False
        for surface in surfaces:
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
            ns = nosearch.get((query.text, surface))
            if ns is not None:
                has_nosearch = True
                if ns.id in brand_ids:
                    brand_in_nosearch = True

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


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


STABILITY_RUNS = 8


def kpi_scorecard(session: Session, tenant_id: int) -> dict:
    """The KPIs an AEO panel converged on (§panel): a prominence-weighted
    Answer Share (north-star), plus prominence, competitive head-to-head,
    sentiment/framing, and run-over-run stability. Pure reads over the
    mention/rank/sentiment data already captured — no LLM, no run spend."""
    brand_name = _brand_name(session, tenant_id)
    search = _latest_results_by_variant(session, tenant_id, ResultVariant.search)
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
            weight = 1.0 / m.rank if m.rank and m.rank > 0 else 0.0
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
        key=lambda x: -x["share"],
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
        key=lambda x: -x["shared"],
    )

    # Stability: brand presence rate across the last few runs.
    by_run: dict[int, list[Result]] = defaultdict(list)
    for r in session.exec(
        select(Result).where(
            Result.tenant_id == tenant_id, Result.variant == ResultVariant.search,
            Result.status == "ok",
        )
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


def outcome(session: Session, tenant_id: int) -> dict:
    """The Outcome view (panel #6): AI-referred sessions + conversions from GA4,
    overlaid on the brand-visibility trend. Answers 'did visibility move the
    business'. Empty until a GA4 property is connected and the nightly pull
    runs."""
    tenant = session.get(Tenant, tenant_id)
    referrals = list(
        session.exec(select(AiReferralDaily).where(AiReferralDaily.tenant_id == tenant_id)).all()
    )

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
        "has_data": bool(referrals),
        "series": series,
        "engine_totals": [
            {"engine": e, **vals}
            for e, vals in sorted(engine_totals.items(), key=lambda kv: -kv[1]["sessions"])
        ],
        "totals": totals,
    }


def _owned_domains(session: Session, tenant_id: int) -> list[str]:
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    return brand.domains if brand else []


def action_plan(session: Session, tenant_id: int) -> dict:
    """The actionable layer (panel #1 + #4): a citation-gap target list — the
    third-party sources that cite rivals in this vertical but not you — and a
    ready-to-work content brief per gap query. Pure reads; briefs are assembled
    from measured data, no LLM spend."""
    brand_name = _brand_name(session, tenant_id)
    owned = _owned_domains(session, tenant_id)

    # Latest search result per (query, surface) and its mention context.
    search = _latest_results_by_variant(session, tenant_id, ResultVariant.search)
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
    if ids:
        for c in session.exec(
            select(Citation).where(Citation.result_id.in_(ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            result = results_by_id.get(c.result_id)
            if result is None or c.source_category != "other" or domain_is_owned(c.domain, owned):
                continue  # skip owned + rivals' own sites; keep pitchable third parties
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
        subtopics = [t for t in by_corpus.get(corpus_of.get(row["query"], ""), [])
                     if t != row["query"]][:6]
        briefs.append({
            "query_id": row["id"],
            "query": row["query"],
            "corpus_tag": row["corpus_tag"],
            "diagnosis": row["diagnosis"],
            "engines_missing": engines_missing,
            "competitors_winning": competitors_winning,
            "target_sources": q_targets,
            "subtopics": subtopics,
            "outline": _brief_outline(row["query"], brand_name, competitors_winning, subtopics),
        })

    return {
        "brand_name": brand_name,
        "targets": targets,
        "briefs": briefs,
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
        "gemini_web": "Gemini (web)", "google_aio": "Google AI Overviews",
    }
    return labels.get(surface, surface)


def _brief_outline(
    query: str, brand: str, competitors: list[str], subtopics: list[str]
) -> list[str]:
    """A pragmatic content outline for a piece that answers this query in a way
    AI answer engines can cite. Deterministic scaffolding, not prose."""
    outline = [
        f"H1: A direct, factual answer to “{query}” in the first 100 words",
        f"H2: Why {brand} — specific, verifiable differentiators (stats, outcomes, dates)",
    ]
    if competitors:
        outline.append(
            f"H2: Honest comparison vs {', '.join(competitors[:3])} — where {brand} fits best"
        )
    for sub in subtopics[:3]:
        outline.append(f"H2: {sub[0].upper() + sub[1:]}")
    outline.append("H2: FAQ — concise Q&A pairs (the format AI answers lift verbatim)")
    outline.append("Include: citable data points, a clear publish date, and structured markup")
    return outline


def queries_intel(session: Session, tenant_id: int) -> dict:
    queries = list(session.exec(select(Query).where(Query.tenant_id == tenant_id)).all())
    classifications = {
        (c.query_text, str(c.surface)): c
        for c in session.exec(
            select(QueryClassification).where(QueryClassification.tenant_id == tenant_id)
        ).all()
    }

    # Latest search-variant result per (query_text, surface).
    latest_results: dict[tuple[str, str], Result] = {}
    for result in session.exec(
        select(Result).where(
            Result.tenant_id == tenant_id, Result.variant == ResultVariant.search
        )
    ).all():
        key = (result.query_text, str(result.surface))
        if key not in latest_results or (result.id or 0) > (latest_results[key].id or 0):
            latest_results[key] = result

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
        classification = None
        for (query_text, surface), c in classifications.items():
            if query_text == query.text:
                classification = {
                    "surface": surface,
                    "web_search_likelihood": c.web_search_likelihood,
                    "signals": c.signals,
                    "classifier_version": c.classifier_version,
                }
                break
        out.append(
            {
                "id": query.id,
                "text": query.text,
                "corpus_tag": query.corpus_tag,
                "active": query.active,
                "classification": classification,
                "latest_results": surfaces,
            }
        )
    return {"queries": out}
