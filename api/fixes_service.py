"""Every fix is an experiment.

A fix is logged with what changed, where and when. When it comes from a
recommendation it also keeps what that recommendation was (its kind, area,
who had to act, the evidence grade), what it would be measured on (the
questions and engines it was ranked on) and what it predicted (the impact
record at that moment). The outcome (api.proof_service) is then comparable
across fixes of the same kind, which is what the ranking will learn from.

Fixes come from three places: "Mark done" on a recommendation, "Mark
shipped" on an Action Plan brief, and the page crawl, which opens a
"detected" fix when a page changed and nobody logged it
(api.page_changes_service)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, col, select

from api.models import (
    FixOutcome,
    Intervention,
    PageChange,
    Recommendation,
    RecommendationStatus,
    utcnow,
)

# Kinds of recommendation that aren't fixes: nothing on any page changes, so
# there is nothing to measure.
NOT_A_FIX = frozenset({"strategy", "connect_logs", "model_change"})
# A page change and a logged fix for the same page this close together are
# the same event.
MATCH_DAYS = 14


class FixError(ValueError):
    """The fix can't be recorded as given (bad date, bad URL)."""


def parse_shipped_at(value: str | None) -> datetime:
    """An ISO date or datetime as UTC; now when empty."""
    if not value:
        return utcnow()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FixError("shipped_at must be an ISO date (YYYY-MM-DD)") from exc
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def clean_url(value: str) -> str:
    url = (value or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise FixError("url must start with http:// or https://")
    return url


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def default_url(rec: Recommendation) -> str:
    """The page a recommendation is about, when it names one of the brand's
    own: where the fix most likely landed."""
    for t in rec.targets or []:
        if t.get("kind") == "Your page" and str(t.get("url", "")).startswith("http"):
            return str(t["url"])
    return ""


def snapshot_of(rec: Recommendation) -> dict[str, Any]:
    """What a recommendation was at the moment a fix for it shipped."""
    scope = rec.scope or {}
    questions = list(scope.get("questions") or ([rec.query_text] if rec.query_text else []))
    return {
        "recommendation_id": rec.id,
        "gap_ref": rec.gap_ref,
        "play": rec.branch,
        "category": rec.category,
        "control": rec.control,
        "evidence": rec.evidence,
        "predicted": {**(rec.impact or {}), "priority": rec.priority} if rec.impact else {},
        "questions": questions,
        "families": list(scope.get("families") or []),
        "query_text": rec.query_text or (questions[0] if len(questions) == 1 else ""),
    }


def log_fix(
    session: Session,
    tenant_id: int,
    *,
    rec: Recommendation | None = None,
    description: str = "",
    url: str = "",
    shipped_at: datetime | None = None,
    by: str = "",
    source: str = "logged",
    query_text: str = "",
    questions: list[str] | None = None,
    subject: str = "",
) -> Intervention:
    """Record a fix. With `rec`, the experiment snapshots the recommendation;
    a second log for the same recommendation on the same day updates the
    first. Page changes the crawl already saw for the same page are attached,
    and a "detected" fix they had opened is folded into this one. Does not
    commit."""
    shipped = _as_utc(shipped_at or utcnow())
    snap = snapshot_of(rec) if rec is not None else {}
    item: Intervention | None = None
    if rec is not None and rec.id is not None:
        for prior in session.exec(
            select(Intervention).where(Intervention.tenant_id == tenant_id,
                                       Intervention.recommendation_id == rec.id,
                                       Intervention.source == source)
        ).all():
            if _as_utc(prior.shipped_at).date() == shipped.date():
                item = prior
                break
    if item is None:
        item = Intervention(tenant_id=tenant_id, query_text=query_text.strip(),
                            created_by=by, source=source, subject=subject)
    for key, value in snap.items():
        setattr(item, key, value)
    if rec is None:
        item.query_text = query_text.strip()
        item.questions = list(questions or ([item.query_text] if item.query_text else []))
    item.description = (description.strip() or (rec.title if rec is not None else "")
                        or item.description)
    item.url = url or item.url or (default_url(rec) if rec is not None else "")
    item.shipped_at = shipped
    session.add(item)
    session.flush()
    if source == "logged":
        _claim_changes(session, item)
    return item


def _claim_changes(session: Session, item: Intervention) -> None:
    """Attach the page changes the crawl saw around the ship date for the
    fix's page, and fold in a detected fix those changes had opened."""
    from api.proof_service import page_path

    path = page_path(item.url)
    if not path or item.id is None:
        return
    shipped = _as_utc(item.shipped_at)
    lo, hi = shipped - timedelta(days=MATCH_DAYS), shipped + timedelta(days=MATCH_DAYS)
    folded: set[int] = set()
    for ch in session.exec(
        select(PageChange).where(PageChange.tenant_id == item.tenant_id,
                                 PageChange.owner == "brand")
    ).all():
        if page_path(ch.url) != path or not lo <= _as_utc(ch.detected_at) <= hi:
            continue
        if ch.intervention_id not in (None, item.id):
            other = session.get(Intervention, ch.intervention_id)
            if other is None or other.source != "detected":
                continue  # already claimed by another logged fix
            folded.add(ch.intervention_id)
        ch.intervention_id = item.id
        session.add(ch)
    for other_id in folded:
        delete_fix(session, other_id, detach=False)


def delete_fix(session: Session, intervention_id: int, *, detach: bool = True) -> None:
    """Remove a fix and its stored outcome. Page changes stay: with `detach`
    they go back to being unclaimed."""
    if detach:
        for ch in session.exec(
            select(PageChange).where(PageChange.intervention_id == intervention_id)
        ).all():
            ch.intervention_id = None
            session.add(ch)
    session.execute(sa_delete(FixOutcome).where(
        col(FixOutcome.intervention_id) == intervention_id))
    item = session.get(Intervention, intervention_id)
    if item is not None:
        session.delete(item)
    session.flush()


def mark_done(
    session: Session,
    rec: Recommendation,
    *,
    description: str = "",
    url: str = "",
    shipped_at: datetime | None = None,
    by: str = "",
) -> Intervention | None:
    """Mark a recommendation done and log the fix as an experiment. Setup
    items and notices are closed without one. Does not commit."""
    rec.status = RecommendationStatus.done
    rec.updated_at = utcnow()
    session.add(rec)
    if rec.branch in NOT_A_FIX or rec.category == "setup":
        return None
    return log_fix(session, rec.tenant_id, rec=rec, description=description, url=url,
                   shipped_at=shipped_at, by=by)


def recommendation_for_question(
    session: Session, tenant_id: int, query_text: str
) -> Recommendation | None:
    """The open page play for a question, if there is one: what an Action
    Plan "mark shipped" is a fix for."""
    rows = session.exec(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            Recommendation.query_text == query_text,
            col(Recommendation.branch).in_(["web_search", "aio", "subquery"]),
            col(Recommendation.status).in_([RecommendationStatus.open,
                                            RecommendationStatus.in_progress]),
        ).order_by(col(Recommendation.priority).desc())
    ).all()
    return rows[0] if rows else None
