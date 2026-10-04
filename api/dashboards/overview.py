"""Overview and Personas: trend, share of voice, AI Overview summary, series notes."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, col, func, select

from api.dashboards.common import (
    _brand_name,
    _branded_query_texts,
    _clean_date,
    _date_in_range,
    _date_window,
    _mean,
    _utc,
)
from api.dashboards.measurement import alerts, mention_rates
from api.models import (
    BrandProfile,
    Mention,
    QueryClassification,
    Result,
    ResultVariant,
    SurfaceCode,
    VisibilityDaily,
)
from engine.processing.citations import domain_is_owned

TREND_DAYS = 90
SOV_DAYS = 30
MAX_MOVERS = 8


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
