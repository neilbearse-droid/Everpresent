"""Agent picks: when someone asks an AI to *do* the job, whose product does
it reach for first?

Questions ("what's the best registrar?") measure being named. Agent prompts
measure being chosen:
  - task prompts ("Register a domain for my bakery and set up email"), where
    an assistant or browsing agent acts for a person
  - coding prompts ("Write a script that registers a domain through an
    API"), where a coding agent picks the vendor and the SDK

They are ordinary queries tagged with corpus `agent_task` or `agent_code`
in the config. The pick is the first tracked brand the answer names (mention
rank 1). An answer that names no tracked brand counts as "no pick", so a
rate always reads against every answer, with its 95% range.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.models import Mention, Query, Result, ResultStatus
from engine.processing.stats import rate_summary

AGENT_CORPORA = {"agent_task": "Task", "agent_code": "Coding"}
WINDOW_DAYS = 28


def _pick_rate(row: dict[str, Any]) -> float:
    return float(row["first_pick"]["rate"])


def agent_picks(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> dict[str, Any]:
    from api.dashboards_service import _brand_name, _surface_label

    kind_of = {
        q.text: q.corpus_tag
        for q in session.exec(
            select(Query).where(Query.tenant_id == tenant_id, Query.active == True,  # noqa: E712
                                col(Query.corpus_tag).in_(list(AGENT_CORPORA)))
        ).all()
    }
    brand = _brand_name(session, tenant_id)
    empty = {"has_prompts": bool(kind_of), "has_data": False, "brand": brand,
             "engines": [], "prompts": [], "kinds": []}
    if not kind_of:
        return empty
    since = datetime.now(UTC) - timedelta(days=days)
    results = session.execute(
        sa_select(col(Result.id), col(Result.surface), col(Result.query_text)).where(
            col(Result.tenant_id) == tenant_id,
            col(Result.status) == ResultStatus.ok,
            col(Result.created_at) >= since,
            col(Result.query_text).in_(list(kind_of)),
        )
    ).all()
    if not results:
        return empty
    firsts: dict[int, tuple[str, str]] = {}
    named: dict[int, set[str]] = defaultdict(set)
    for rid, etype, name, rank in session.execute(
        sa_select(col(Mention.result_id), col(Mention.entity_type), col(Mention.entity_name),
                  col(Mention.rank)).where(
            col(Mention.result_id).in_([r[0] for r in results])
        )
    ).all():
        named[rid].add(etype)
        if rank == 1:
            firsts[rid] = (etype, name)

    def summarise(rows: list[Any]) -> dict[str, Any]:
        picks = Counter(firsts[r[0]][1] if r[0] in firsts else None for r in rows)
        n = len(rows)
        mine = sum(1 for r in rows if firsts.get(r[0], ("", ""))[0] == "brand")
        rival = next(((nm, c) for nm, c in picks.most_common() if nm and nm != brand), None)
        return {
            "first_pick": rate_summary(mine, n),
            "named": rate_summary(sum(1 for r in rows if "brand" in named.get(r[0], ())), n),
            "no_pick": round(100.0 * picks.get(None, 0) / n, 1),
            "top_rival": {"name": rival[0], "rate": round(100.0 * rival[1] / n, 1)}
            if rival else None,
            "leader": next((nm for nm, _ in picks.most_common() if nm), None),
        }

    by_engine: dict[str, list[Any]] = defaultdict(list)
    by_prompt: dict[str, list[Any]] = defaultdict(list)
    by_kind: dict[str, list[Any]] = defaultdict(list)
    for r in results:
        by_engine[str(r[1])].append(r)
        by_prompt[r[2]].append(r)
        by_kind[kind_of[r[2]]].append(r)
    return {
        "has_prompts": True,
        "has_data": True,
        "brand": brand,
        "days": days,
        "overall": summarise(list(results)),
        "kinds": [{"kind": AGENT_CORPORA[k], **summarise(v)} for k, v in sorted(by_kind.items())],
        "engines": sorted(
            ({"surface": s, "label": _surface_label(s), **summarise(v)}
             for s, v in by_engine.items()),
            key=_pick_rate, reverse=True,
        ),
        "prompts": sorted(
            ({"text": t, "kind": AGENT_CORPORA[kind_of[t]], **summarise(v)}
             for t, v in by_prompt.items()),
            key=lambda p: (_pick_rate(p), str(p["text"])),
        ),
    }
