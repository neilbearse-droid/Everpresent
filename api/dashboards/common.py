"""Shared helpers for the dashboard reads: names, date windows, the
branded-query filter, latest results per variant."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, col, func, select

from api.models import (
    BrandProfile,
    Citation,
    Mention,
    Query,
    Result,
    ResultVariant,
    Tenant,
)


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


def _date_window(
    start: str | None, end: str | None
) -> tuple[datetime | None, datetime | None]:
    """Inclusive ISO-date range → UTC datetime bounds (end is exclusive, +1 day).
    Invalid values are ignored rather than erroring — a bad filter should
    degrade to 'all time', not break the dashboard."""

    def parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        # Convert an offset-aware input to UTC; assume UTC for a naive one
        # (don't silently reinterpret an offset as UTC).
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)

    lo = parse(start)
    hi = parse(end)
    if hi is not None:
        try:
            hi = hi + timedelta(days=1)
        except OverflowError:  # e.g. end=9999-12-31: no upper bound
            hi = None
    return lo, hi


def _utc(dt: datetime) -> datetime:
    """A window bound as aware UTC, the form the datetime columns bind."""
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _in_window(dt: datetime, lo: datetime | None, hi: datetime | None) -> bool:
    d = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return (lo is None or d >= lo) and (hi is None or d < hi)


def _date_in_range(date: str, start: str | None, end: str | None) -> bool:
    """ISO date strings compare lexicographically, so plain string bounds work."""
    return (not start or date >= start) and (not end or date <= end)


def _clean_date(value: str | None) -> str | None:
    """Normalize to a bare YYYY-MM-DD string (or None if unparseable). Callers
    string-compare these against stored `date` columns, so a datetime input
    like '2026-07-01T00:00:00' must be truncated — otherwise the lexicographic
    compare drops the boundary day ('2026-07-01' >= '2026-07-01T…' is False)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


# Agent prompts ("pick a provider and do it for me") are measured as their
# own category (Agent picks), not in the visibility numbers.
AGENT_CORPUS_TAGS = frozenset({"agent_task", "agent_code"})


def _off_score_query_texts(session: Session, tenant_id: int) -> frozenset[str]:
    """Query texts kept out of the visibility layer (mention rate, answer
    share, share of voice, the score): branded questions, which name the
    brand by design, and agent prompts, which are their own category."""
    return frozenset(
        q.text
        for q in session.exec(select(Query).where(Query.tenant_id == tenant_id)).all()
        if q.branded or q.corpus_tag in AGENT_CORPUS_TAGS
    )


def _branded_query_texts(session: Session, tenant_id: int) -> frozenset[str]:
    """Query texts flagged branded — probes of what the model says about the
    brand. Matched by value (results snapshot query_text), so a re-import that
    changes the flag re-scopes cleanly on the next read."""
    return frozenset(
        q.text
        for q in session.exec(
            select(Query).where(
                Query.tenant_id == tenant_id,
                Query.branded == True,  # noqa: E712
            )
        ).all()
    )


def _latest_results_by_variant(
    session: Session,
    tenant_id: int,
    variant: ResultVariant,
    lo: datetime | None = None,
    hi: datetime | None = None,
    scope: str = "all",
) -> dict[tuple[str, str], Result]:
    """Newest result per (query_text, surface) for one variant, restricted to
    the [lo, hi) window when given — i.e. the state 'as of' the range's end.

    scope splits the two analysis layers (branded-query feedback):
      "all"          — every query (default; unchanged behaviour)
      "competitive"  — exclude branded queries and agent prompts (the visibility layer)
      "unbranded"    — exclude branded queries only (agent prompts kept)
      "branded"      — only branded queries (the brand-knowledge layer)"""
    branded = (
        _branded_query_texts(session, tenant_id)
        if scope in ("branded", "unbranded") else frozenset()
    )
    off_score = (
        _off_score_query_texts(session, tenant_id) if scope == "competitive" else frozenset()
    )
    if scope == "branded" and not branded:
        return {}
    # The database picks the newest id per (query, surface); only those rows
    # are loaded. Loading the whole history to keep a few dozen rows cost
    # seconds and hundreds of MB per call once a tenant has months of runs.
    conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.variant == variant,
        Result.status == "ok",
    ]
    if lo is not None:
        conds.append(col(Result.created_at) >= _utc(lo))
    if hi is not None:
        conds.append(col(Result.created_at) < _utc(hi))
    if scope == "competitive" and off_score:
        conds.append(col(Result.query_text).not_in(off_score))
    if scope == "unbranded" and branded:
        conds.append(col(Result.query_text).not_in(branded))
    if scope == "branded":
        conds.append(col(Result.query_text).in_(branded))
    newest = (
        select(func.max(Result.id))
        .where(*conds)
        .group_by(col(Result.query_text), col(Result.surface))
    )
    latest: dict[tuple[str, str], Result] = {}
    # Ordered by id, as the history scan was: callers iterate this dict and
    # some keep the first form they see, so row order must not depend on the
    # database (Postgres and SQLite return IN-subquery rows differently).
    for result in session.exec(
        select(Result).where(col(Result.id).in_(newest)).order_by(col(Result.id))
    ).all():
        latest[(result.query_text, str(result.surface))] = result
    return latest


def _brand_and_cited_ids(
    session: Session, result_ids: list[int]
) -> tuple[set[int], set[int]]:
    """(brand-mentioned ids, brand-cited ids) over a set of results, in two
    bounded queries rather than N per-result lookups."""
    brand_ids: set[int] = set()
    cited_ids: set[int] = set()
    if not result_ids:
        return brand_ids, cited_ids
    for m in session.exec(
        select(Mention).where(
            Mention.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
            Mention.entity_type == "brand",
        )
    ).all():
        brand_ids.add(m.result_id)
    for c in session.exec(
        select(Citation).where(
            Citation.result_id.in_(result_ids),  # pyright: ignore[reportAttributeAccessIssue]
            Citation.source_category == "brand",
        )
    ).all():
        cited_ids.add(c.result_id)
    return brand_ids, cited_ids


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _owned_domains(session: Session, tenant_id: int) -> list[str]:
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    return brand.domains if brand else []


def _surface_label(surface: str) -> str:
    """Server-side surface label mirror (the client also labels); keeps briefs
    readable if rendered outside the app (e.g. an exported report)."""
    labels = {
        "openai_api": "ChatGPT", "perplexity_api": "Perplexity", "claude_api": "Claude",
        "gemini_api": "Gemini", "chatgpt_web": "ChatGPT (web)",
        "perplexity_web": "Perplexity (web)",
        "gemini_web": "Gemini (web)", "copilot_web": "Microsoft Copilot",
        "google_aio": "Google AI Overviews",
        "google_ai_mode": "Google AI Mode",
    }
    return labels.get(surface, surface)
