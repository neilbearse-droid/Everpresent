"""Queries: per-question intelligence."""

from typing import Any

from sqlmodel import Session, col, func, select

from api.dashboards.common import _date_window, _utc
from api.models import (
    Mention,
    Query,
    QueryClassification,
    Result,
    ResultStatus,
    ResultVariant,
)


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
