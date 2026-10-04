"""Sponsored units: who pays to appear next to AI answers.

Kept entirely apart from organic visibility (those units are cut out of the
answer text before mentions are counted). Reports, per engine, how often an
answer came with any paid unit, and the advertisers' share of those units."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select as sa_select
from sqlmodel import Session, col

from api.models import Result, ResultStatus, ResultVariant, SponsoredUnit

WINDOW_DAYS = 28


def ads_report(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> dict[str, Any]:
    from api.dashboards_service import _brand_name, _surface_label

    since = datetime.now(UTC) - timedelta(days=days)
    answers = Counter(
        str(s) for (s,) in session.execute(
            sa_select(col(Result.surface)).where(
                col(Result.tenant_id) == tenant_id, col(Result.status) == ResultStatus.ok,
                col(Result.variant) == ResultVariant.search, col(Result.created_at) >= since,
            )
        ).all()
    )
    units = session.execute(
        sa_select(col(SponsoredUnit.result_id), col(Result.surface),
                  col(SponsoredUnit.advertiser), col(SponsoredUnit.advertiser_type),
                  col(SponsoredUnit.title))
        .join(Result, col(Result.id) == col(SponsoredUnit.result_id))
        .where(col(SponsoredUnit.tenant_id) == tenant_id, col(Result.created_at) >= since)
    ).all()
    brand = _brand_name(session, tenant_id)
    with_ads: dict[str, set[int]] = defaultdict(set)
    by_adv: Counter[tuple[str, str]] = Counter()
    examples: dict[str, str] = {}
    for rid, surface, adv, kind, title in units:
        with_ads[str(surface)].add(rid)
        by_adv[(adv, kind)] += 1
        examples.setdefault(adv, title)
    total = sum(by_adv.values())
    return {
        "brand": brand,
        "days": days,
        "has_data": total > 0,
        "answers": sum(answers.values()),
        "units": total,
        "engines": [
            {"surface": s, "label": _surface_label(s), "answers": n,
             "with_ads": len(with_ads.get(s, ())),
             "ad_rate": round(100.0 * len(with_ads.get(s, ())) / n, 1) if n else 0.0}
            for s, n in sorted(answers.items(), key=lambda kv: -len(with_ads.get(kv[0], ())))
        ],
        "advertisers": [
            {"name": adv, "type": kind, "units": n, "share": round(100.0 * n / total, 1),
             "example": examples.get(adv, "")}
            for (adv, kind), n in by_adv.most_common(15)
        ],
        "brand_share": round(100.0 * sum(n for (a, k), n in by_adv.items() if k == "brand")
                             / total, 1) if total else 0.0,
    }
