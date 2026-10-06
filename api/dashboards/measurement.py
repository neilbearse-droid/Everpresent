"""Measurement: mention rates with ranges and real-change tests, alerts, the KPI scorecard."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from api.dashboards.action_plan import _lost_citations
from api.dashboards.common import (
    _brand_and_cited_ids,
    _brand_name,
    _branded_query_texts,
    _date_window,
    _latest_results_by_variant,
    _pct,
    _stdev,
    _surface_label,
    _utc,
)
from api.models import (
    AccuracyFinding,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
)
from engine.processing.stats import change_verdict, rate_summary

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
        "by_topic": topic_scorecard(session, tenant_id, start, end),
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


# Corpus tags with a fixed meaning get a readable name; any other tag is the
# client's own topic ("sensitive", "organic") and is shown title-cased.
TOPIC_NAMES = {"core": "General", "agent_task": "Agent tasks", "agent_code": "Agent coding"}
AGENT_TOPICS = {"agent_task", "agent_code"}


_ACRONYMS = {"ai", "seo", "crm", "api", "spf", "uv", "diy", "b2b", "b2c", "smb", "llm"}


def _topic_label(tag: str) -> str:
    tag = (tag or "core").strip()
    if tag in TOPIC_NAMES:
        return TOPIC_NAMES[tag]
    words = tag.replace("_", " ").replace("-", " ").split()
    words = [w.upper() if w.lower() in _ACRONYMS else w.lower() for w in words]
    label = " ".join(words)
    return label[:1].upper() + label[1:]


def topic_scorecard(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> list[dict]:
    """The headline metrics per question topic (the query's corpus tag), so a
    strong topic can't hide a weak one in the overall number.

    Competitive and agent topics get mention rate (pooled over the window,
    with range and real-change test), answer share, lead rate and the rival
    taking the most share. Branded questions are one separate row, because
    they name the brand by design: there the useful numbers are sentiment,
    how often rivals get named in an answer about you, and how often your own
    site is cited."""
    brand_name = _brand_name(session, tenant_id)
    topic_of: dict[str, tuple[str, str]] = {}  # query text -> (topic, kind)
    for q in session.exec(select(Query).where(Query.tenant_id == tenant_id)).all():
        if q.branded:
            topic_of[q.text] = (f"About {brand_name}", "branded")
        elif q.corpus_tag in AGENT_TOPICS:
            topic_of[q.text] = (_topic_label(q.corpus_tag), "agent")
        else:
            topic_of[q.text] = (_topic_label(q.corpus_tag), "competitive")
    if not topic_of:
        return []

    # Mention rate per topic: every ok search answer in the window, split in
    # halves for the change test (same rules as mention_rates).
    lo, hi = _date_window(start, end)
    hi_eff = _utc(hi) if hi is not None else datetime.now(UTC)
    lo_eff = _utc(lo) if lo is not None else hi_eff - timedelta(days=MENTION_WINDOW_DAYS)
    mid = lo_eff + (hi_eff - lo_eff) / 2
    brand_hits = (
        select(col(Mention.result_id))
        .where(Mention.tenant_id == tenant_id, Mention.entity_type == "brand")
        .distinct()
        .subquery()
    )
    second_half = case((col(Result.created_at) >= mid, 1), else_=0)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    questions: dict[str, set[str]] = defaultdict(set)
    for qtext, half, n, k in session.exec(
        select(col(Result.query_text), second_half,
               func.count(col(Result.id)), func.count(brand_hits.c.result_id))
        .outerjoin(brand_hits, brand_hits.c.result_id == col(Result.id))
        .where(Result.tenant_id == tenant_id, Result.variant == ResultVariant.search,
               Result.status == ResultStatus.ok,
               col(Result.created_at) >= lo_eff, col(Result.created_at) < hi_eff)
        .group_by(col(Result.query_text), second_half)
    ).all():
        if qtext not in topic_of:
            continue  # a question that was since removed
        topic = topic_of[qtext][0]
        questions[topic].add(qtext)
        c = counts[topic]
        c[2 if half else 0] += int(k)
        c[3 if half else 1] += int(n)

    # Share, lead rate, sentiment, rivals and citations: the latest answer per
    # (question, engine) in the window, like the rest of the scorecard.
    latest = list(_latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="all").values())
    latest = [r for r in latest if r.query_text in topic_of]
    ids = [r.id for r in latest if r.id is not None]
    mentions: dict[int, list[Mention]] = defaultdict(list)
    for m in (session.exec(select(Mention).where(col(Mention.result_id).in_(ids))).all()
              if ids else []):
        mentions[m.result_id].append(m)
    _brand_ids, cited_ids = _brand_and_cited_ids(session, ids)

    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "weight": defaultdict(float), "total": 0.0, "present": 0, "leads": 0, "measured": 0,
        "with_rival": 0, "cited": 0, "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
    })
    for r in latest:
        a = agg[topic_of[r.query_text][0]]
        a["measured"] += 1
        ms = mentions.get(r.id or -1, [])
        for m in ms:
            w = 1.0 / m.rank if m.rank >= 1 else 0.0
            a["total"] += w
            a["weight"][brand_name if m.entity_type == "brand" else m.entity_name] += w
        if any(m.entity_type != "brand" for m in ms):
            a["with_rival"] += 1
        if (r.id or -1) in cited_ids:
            a["cited"] += 1
        brand_ms = [m for m in ms if m.entity_type == "brand"]
        if brand_ms:
            best = min(brand_ms, key=lambda m: m.rank or 999)
            a["present"] += 1
            a["leads"] += best.rank == 1
            a["sentiment"][best.sentiment] = a["sentiment"].get(best.sentiment, 0) + 1

    kinds = {topic: kind for topic, kind in topic_of.values()}
    rows: list[dict] = []
    for topic in set(counts) | set(agg):
        c, a = counts[topic], agg[topic]
        rivals = {n: w for n, w in a["weight"].items() if n != brand_name}
        top = max(rivals, key=lambda n: rivals[n]) if rivals else None
        rows.append({
            "topic": topic,
            "kind": kinds[topic],
            "questions": len(questions[topic]),
            **rate_summary(c[0] + c[2], c[1] + c[3]),
            "change": change_verdict(c[0], c[1], c[2], c[3]),
            "answer_share": _pct(a["weight"].get(brand_name, 0.0), a["total"]),
            "lead_rate": _pct(a["leads"], a["present"]),
            "top_rival": ({"name": top, "share": _pct(rivals[top], a["total"])}
                          if top else None),
            "sentiment": a["sentiment"],
            "rivals_named_rate": _pct(a["with_rival"], a["measured"]),
            "cited_rate": _pct(a["cited"], a["measured"]),
        })
    order = {"competitive": 0, "agent": 1, "branded": 2}
    return sorted(rows, key=lambda r: (order[r["kind"]], -r["answers"], r["topic"]))
