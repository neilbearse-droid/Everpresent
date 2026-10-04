"""Fan-out: the sub-queries engines search, and who wins each."""

from collections import defaultdict
from datetime import datetime

from sqlmodel import Session, select

from api.dashboards.common import (
    _brand_name,
    _date_window,
    _in_window,
    _latest_results_by_variant,
    _surface_label,
)
from api.fanout_service import PRIORITY_RANK, shard_norm
from api.fanout_service import names_present as _names_present
from api.models import (
    BrandProfile,
    Competitor,
    FanoutShard,
    Mention,
    Result,
    ResultVariant,
    Tenant,
)


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
