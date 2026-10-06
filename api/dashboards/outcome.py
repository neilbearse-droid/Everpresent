"""Outcome: GA4 AI referrals and the intervention ledger."""

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from api.dashboards.common import (
    _as_utc,
    _brand_name,
    _clean_date,
    _date_in_range,
    _mean,
    _off_score_query_texts,
)
from api.models import (
    AiReferralDaily,
    Intervention,
    Mention,
    Result,
    ResultVariant,
    Tenant,
    VisibilityDaily,
)


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
        {q for (q, _s, _c, _r) in rows} - treated_queries
        - _off_score_query_texts(session, tenant_id)
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
