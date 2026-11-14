"""What changed on the pages engines cite, whether or not anyone told us.

Each crawl compares a page with the last version we kept: the brand's own
cited pages, the third-party pages engines cite, and rivals' cited pages. A
new version is stored only when something worth reporting changed, so a
change is dated to the gap between two crawls. Each change is one plain
event: a price appeared, the date was refreshed, a sub-question got its own
section, the brand turned up on a list.

Changes that can move answers ("material") become experiments. On the
brand's own page they attach to the fix someone logged for that page, or
open a "detected" fix when nobody did. On a rival's page they open a
detected fix measured on that rival's mentions: someone else's experiment,
read for free. Nothing here calls a model or the network."""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, col, select

from api.models import (
    Citation,
    Intervention,
    PageChange,
    PageSnapshot,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    utcnow,
)

# The page state a version is made of.
TRACKED = (
    "has_price", "has_updated_date", "updated_on", "latest_year", "has_rating",
    "statistic_count", "word_count", "has_answer_capsule", "has_tables", "json_ld",
    "faq_schema", "noindex", "headings", "fact_conflicts",
)

# Thresholds: small wobble between two fetches of the same page (an ad, a
# rotating testimonial, a rolling "updated today") must not read as a change.
MIN_WORDS_DELTA = 150        # and at least a quarter of the page
MIN_STATS_DELTA = 5          # and at least half again as many
MIN_DATE_JUMP_DAYS = 30      # a rolling date moves a day at a time
CITED_WINDOW_DAYS = 28
MATCH_DAYS = 14              # a change this close to a fix is that fix

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"the", "a", "an", "for", "of", "to", "in", "on", "and", "or", "with", "is",
                   "are", "what", "which", "how", "do", "does", "your", "you", "my", "i"})


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def tracked_state(page: dict) -> dict[str, Any]:
    """The comparable state of a crawled page (a parsed crawl row)."""
    features = page.get("features") or {}
    state: dict[str, Any] = {k: features.get(k) for k in TRACKED if k in features}
    state["brand_found"] = bool(page.get("brand_found"))
    state["competitors_found"] = sorted(page.get("competitors_found") or [])
    return state


def fingerprint(state: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def covers(heading: str, question: str) -> bool:
    """Does a section heading answer a sub-question? Three quarters of the
    question's content words in the heading, and at least two of them."""
    q, h = _tokens(question), _tokens(heading)
    if len(q) < 2:
        return False
    return len(q & h) >= max(2, round(0.75 * len(q)))


def _change(kind: str, summary: str, material: bool, **detail: Any) -> dict[str, Any]:
    return {"kind": kind, "summary": summary, "material": material, "detail": detail}


def diff(old: dict[str, Any], new: dict[str, Any], *, owner: str,
         subquestions: Sequence[str] = ()) -> list[dict[str, Any]]:
    """The reportable changes between two versions of a page. `owner` is
    whose page it is (brand | competitor | other); `subquestions` are the
    sub-searches the brand is absent from, checked against new sections on
    the brand's own pages. A key missing from the old version (it predates
    that check) is never a change."""
    out: list[dict[str, Any]] = []

    def flipped_on(key: str) -> bool:
        return key in old and not old.get(key) and bool(new.get(key))

    def flipped_off(key: str) -> bool:
        return bool(old.get(key)) and key in new and not new.get(key)

    if flipped_on("has_price"):
        out.append(_change("price_added", "Prices are now stated on the page", True))
    elif flipped_off("has_price"):
        out.append(_change("price_removed", "Prices are no longer stated on the page", True))

    was, now = str(old.get("updated_on") or ""), str(new.get("updated_on") or "")
    if was and now and now > was:
        jump = (date.fromisoformat(now) - date.fromisoformat(was)).days
        if jump >= MIN_DATE_JUMP_DAYS:
            out.append(_change("date_refreshed",
                               f"“Updated” date moved from {was} to {now}", True,
                               before=was, after=now))
    elif "updated_on" in old and not was and now:
        out.append(_change("date_added", f"The page now shows when it was updated ({now})",
                           True, after=now))
    elif not now and flipped_on("has_updated_date"):
        out.append(_change("date_added", "The page now shows when it was updated", True))
    else:
        y0, y1 = int(old.get("latest_year") or 0), int(new.get("latest_year") or 0)
        if y0 and y1 > y0 and not (was or now):
            out.append(_change("year_refreshed", f"Now cites {y1} (was {y0})", True,
                               before=y0, after=y1))

    if flipped_on("has_rating"):
        out.append(_change("rating_added", "A rating or review score now shows", True))

    w0, w1 = int(old.get("word_count") or 0), int(new.get("word_count") or 0)
    if w0 >= 50 and abs(w1 - w0) >= max(MIN_WORDS_DELTA, 0.25 * w0):
        grew = w1 > w0
        out.append(_change("content_expanded" if grew else "content_cut",
                           f"The page {'grew' if grew else 'shrank'} from about {w0:,} to "
                           f"{w1:,} words", True, before=w0, after=w1))
    s0, s1 = int(old.get("statistic_count") or 0), int(new.get("statistic_count") or 0)
    if "statistic_count" in old and s1 - s0 >= max(MIN_STATS_DELTA, 0.5 * s0):
        out.append(_change("data_added", f"Data points rose from {s0} to {s1}", True,
                           before=s0, after=s1))

    if isinstance(old.get("headings"), list) and isinstance(new.get("headings"), list):
        before = {h.lower() for h in old["headings"]}
        added = [h for h in new["headings"] if h.lower() not in before]
        covered = [q for q in subquestions if any(covers(h, q) for h in added)]
        for q in covered[:5]:
            out.append(_change("subquestion_covered", f"Now has a section for “{q}”", True,
                               question=q))
        if added and old["headings"] and not covered:
            shown = ", ".join(f"“{h}”" for h in added[:3])
            more = f" and {len(added) - 3} more" if len(added) > 3 else ""
            out.append(_change("sections_added", f"New sections: {shown}{more}", True,
                               added=added[:10]))

    if flipped_on("noindex"):
        out.append(_change("noindex_added", "A noindex tag was added: engines that search "
                           "can no longer retrieve the page", True))
    elif flipped_off("noindex"):
        out.append(_change("noindex_removed", "The noindex tag is gone", True))
    for key, label in (("has_answer_capsule", "A short direct answer now sits under a "
                                              "question heading"),
                       ("has_tables", "A table was added"),
                       ("json_ld", "Structured data (JSON-LD) was added"),
                       ("faq_schema", "FAQ markup was added")):
        if flipped_on(key):
            out.append(_change(f"{key.removeprefix('has_')}_added", label, False))

    if owner == "brand":
        c0, c1 = old.get("fact_conflicts"), new.get("fact_conflicts")
        if c0 and c1 is not None and not c1:
            out.append(_change("fact_conflict_fixed",
                               "The page no longer contradicts your fact sheet", True))
        elif c0 is not None and not c0 and c1:
            out.append(_change("fact_conflict_new",
                               "The page now contradicts your fact sheet", True))
    else:
        if not old.get("brand_found") and new.get("brand_found"):
            out.append(_change("brand_added", "You now appear on this page", True))
        elif old.get("brand_found") and not new.get("brand_found"):
            out.append(_change("brand_removed", "You no longer appear on this page", True))
    if owner == "other":
        r0 = set(old.get("competitors_found") or [])
        r1 = set(new.get("competitors_found") or [])
        if added := sorted(r1 - r0):
            verb = "appears" if len(added) == 1 else "appear"
            out.append(_change("rival_added", f"{', '.join(added)} now {verb} on this page",
                               True, added=added))
        if removed := sorted(r0 - r1):
            verb = "appears" if len(removed) == 1 else "appear"
            out.append(_change("rival_removed",
                               f"{', '.join(removed)} no longer {verb} on this page", False,
                               removed=removed))
    return out


def record_crawl(session: Session, tenant_id: int, pages: list[dict], *,
                 subquestions: Sequence[str] = (), now: datetime | None = None) -> dict[str, int]:
    """Version the pages of one crawl and record what changed. `pages` are the
    crawl's parsed rows (url, owner, owner_name, status, brand_found,
    competitors_found, features); only pages that loaded are versioned, so a
    blocked fetch never reads as a change. Does not commit."""
    now = _as_utc(now or utcnow())
    stats = {"versions": 0, "changes": 0, "experiments": 0}
    new_changes: list[PageChange] = []
    for page in pages:
        if page.get("status") != "ok" or not page.get("url"):
            continue
        owner = page.get("owner") or "other"
        state = tracked_state(page)
        latest = session.exec(
            select(PageSnapshot).where(PageSnapshot.tenant_id == tenant_id,
                                       PageSnapshot.url == page["url"])
            .order_by(col(PageSnapshot.first_seen_at).desc(), col(PageSnapshot.id).desc())
        ).first()
        changes: list[dict[str, Any]] = []
        if latest is not None:
            prior = {**(latest.features or {}), "brand_found": latest.brand_found,
                     "competitors_found": list(latest.competitors_found or [])}
            changes = diff(prior, state, owner=owner,
                           subquestions=subquestions if owner == "brand" else ())
            if not changes:
                latest.last_seen_at = now
                session.add(latest)
                continue
        features = {k: v for k, v in state.items()
                    if k not in ("brand_found", "competitors_found")}
        session.add(PageSnapshot(
            tenant_id=tenant_id, url=page["url"], owner=owner,
            owner_name=page.get("owner_name") or "", status="ok",
            http_status=page.get("http_status"), brand_found=state["brand_found"],
            competitors_found=state["competitors_found"], features=features,
            fingerprint=fingerprint(state), first_seen_at=now, last_seen_at=now))
        stats["versions"] += 1
        for ch in changes:
            assert latest is not None
            row = PageChange(
                tenant_id=tenant_id, url=page["url"], owner=owner,
                owner_name=page.get("owner_name") or "", kind=ch["kind"],
                summary=ch["summary"], detail=ch["detail"], material=ch["material"],
                changed_after=_as_utc(latest.last_seen_at), detected_at=now)
            session.add(row)
            new_changes.append(row)
    session.flush()
    stats["changes"] = len(new_changes)
    stats["experiments"] = _open_experiments(session, tenant_id, new_changes)
    return stats


def _questions_citing(session: Session, tenant_id: int, url: str, until: datetime) -> list[str]:
    """Competitive questions whose answers cited this page in the weeks
    before a change: what the change is measured on."""
    from api.dashboards.common import _off_score_query_texts

    since = until - timedelta(days=CITED_WINDOW_DAYS)
    texts = set(session.exec(
        select(col(Result.query_text))
        .join(Citation, col(Citation.result_id) == col(Result.id))
        .where(Citation.tenant_id == tenant_id, Citation.url == url,
               Result.status == ResultStatus.ok, Result.variant == ResultVariant.search,
               col(Result.created_at) >= since)
        .distinct()
    ).all())
    return sorted(texts - _off_score_query_texts(session, tenant_id))


def _recommendation_for_page(session: Session, tenant_id: int, url: str,
                             owner: str) -> Recommendation | None:
    """The open recommendation a change on this page most likely answers: one
    that names the page, or the source play for the page's site."""
    from api.proof_service import page_path

    host = (urlsplit(url).hostname or "").removeprefix("www.")
    path = page_path(url)
    best: Recommendation | None = None
    for rec in session.exec(
        select(Recommendation).where(
            Recommendation.tenant_id == tenant_id,
            col(Recommendation.status).in_([RecommendationStatus.open,
                                            RecommendationStatus.in_progress]))
        .order_by(col(Recommendation.priority).desc())
    ).all():
        if owner == "brand":
            named = any(
                (urlsplit(str(t.get("url", ""))).hostname or "").removeprefix("www.") == host
                and page_path(str(t.get("url", ""))) == path
                for t in rec.targets or [] if t.get("url"))
            if named or rec.gap_ref.endswith(f":{path}") or rec.gap_ref.endswith(url):
                best = rec
                break
        elif rec.gap_ref == f"source:{host}":
            best = rec
            break
    return best


def _open_experiments(session: Session, tenant_id: int, changes: list[PageChange]) -> int:
    """Turn a crawl's material changes into experiments: attach them to the
    logged fix for the same page, or open a detected one."""
    from api import fixes_service
    from api.proof_service import page_path

    by_page: dict[tuple[str, str], list[PageChange]] = defaultdict(list)
    for ch in changes:
        if not ch.material:
            continue
        if ch.owner == "brand" or ch.kind in ("brand_added", "brand_removed"):
            # The brand's own page, or the brand turning up on (or dropping
            # off) someone else's, a rival's comparison page included: the
            # brand's experiment.
            by_page[(ch.url, "")].append(ch)
        elif ch.owner == "competitor":
            by_page[(ch.url, ch.owner_name)].append(ch)
        elif ch.kind == "rival_added":
            for name in ch.detail.get("added") or []:
                by_page[(ch.url, name)].append(ch)
    opened = 0
    for (url, subject), group in by_page.items():
        first = group[0]
        detected = _as_utc(first.detected_at)
        since = _as_utc(first.changed_after)
        # Best estimate of when it happened: halfway between the two crawls.
        shipped = since + (detected - since) / 2
        path = page_path(url)
        lo, hi = shipped - timedelta(days=MATCH_DAYS), detected + timedelta(days=MATCH_DAYS)
        match: Intervention | None = None
        for item in session.exec(
            select(Intervention).where(Intervention.tenant_id == tenant_id,
                                       Intervention.subject == subject)
        ).all():
            if page_path(item.url) != path or not lo <= _as_utc(item.shipped_at) <= hi:
                continue
            if match is None or (item.source == "logged" and match.source != "logged"):
                match = item
        summary = "; ".join(dict.fromkeys(ch.summary for ch in group))
        if match is None:
            rec = (None if subject else
                   _recommendation_for_page(session, tenant_id, url, first.owner))
            questions = _questions_citing(session, tenant_id, url, detected)
            if rec is None and not questions:
                continue  # nothing to measure it on
            match = fixes_service.log_fix(
                session, tenant_id, rec=rec, description=summary, url=url, shipped_at=shipped,
                by="crawl", source="detected", questions=questions, subject=subject)
            opened += 1
        elif match.source == "detected" and summary not in match.description:
            match.description = f"{match.description}; {summary}"[:2000]
            session.add(match)
        for ch in group:
            # A rival_added change can feed several rivals' experiments; it
            # is linked to the first.
            if ch.intervention_id is None:
                ch.intervention_id = match.id
                session.add(ch)
    session.flush()
    return opened


_OWNER_LABEL = {"brand": "Your page", "competitor": "Rival's page", "other": "Cited page"}


def recent_changes(session: Session, tenant_id: int, days: int = 60,
                   limit: int = 40) -> list[dict[str, Any]]:
    """The changes seen on crawled pages lately, newest first: one entry per
    page per crawl, listing everything that changed on it between the two."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.exec(
        select(PageChange).where(PageChange.tenant_id == tenant_id,
                                 col(PageChange.detected_at) >= since)
        .order_by(col(PageChange.detected_at).desc(), col(PageChange.id))
    ).all()
    grouped: dict[tuple[str, datetime], dict[str, Any]] = {}
    for ch in rows:
        entry = grouped.setdefault((ch.url, ch.detected_at), {
            "id": ch.id, "url": ch.url, "owner": ch.owner,
            "owner_label": (ch.owner_name if ch.owner == "competitor" and ch.owner_name
                            else _OWNER_LABEL.get(ch.owner, "Cited page")),
            "kinds": [], "summaries": [], "material": False,
            "between": [_as_utc(ch.changed_after).date().isoformat(),
                        _as_utc(ch.detected_at).date().isoformat()],
            "intervention_id": None,
        })
        entry["kinds"].append(ch.kind)
        entry["summaries"].append(ch.summary)
        entry["material"] = entry["material"] or ch.material
        if entry["intervention_id"] is None:
            entry["intervention_id"] = ch.intervention_id
    return list(grouped.values())[:limit]
