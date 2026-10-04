"""Brand: accuracy findings, brand knowledge, whitespace (names we don't track)."""

from collections import defaultdict

from sqlmodel import Session, select

from api.dashboards.common import (
    _brand_name,
    _date_window,
    _latest_results_by_variant,
    _pct,
    _surface_label,
)
from api.models import (
    AccuracyFinding,
    BrandFact,
    Mention,
    ResultVariant,
    UntrackedMention,
)


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
