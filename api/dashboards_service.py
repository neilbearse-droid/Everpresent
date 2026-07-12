"""Read-side aggregation for the client dashboards (§7.1 Overview, Personas,
Queries). Pure Postgres reads over the processed rollups — no LLM, no
provider calls."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from api.models import (
    BrandProfile,
    Mention,
    Query,
    QueryClassification,
    Result,
    ResultVariant,
    Tenant,
    VisibilityDaily,
)

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
