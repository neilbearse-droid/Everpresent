"""Proof of results: did a shipped fix move anything, beyond the tide?

For each logged intervention, compares equal windows before and after the
ship date on every signal we hold, each against a control:

  mentions     brand named in answers to the fixed query, vs all untouched
               non-branded queries. Tested for a real change (two-proportion
               test), and reported as a difference-in-differences.
  bot reads    AI bots fetching the fixed page (indexing + live user fetches),
               vs every other page. Needs Agent Analytics logs.
  search AI    Search Console / Bing AI impressions or citations for the
               fixed page, vs every other page. Needs a first-party import.
  referrals    GA4 AI-referred sessions. Sitewide only: GA4 doesn't tie a
               session to one fix, so this is context, never proof.

Counts (reads, impressions, sessions) carry no sampling model here, so they
are labelled directional; only the mention change is called "real".
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.models import (
    AgentTrafficDaily,
    AiReferralDaily,
    FirstPartyDaily,
    Intervention,
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
)
from engine.processing.stats import change_verdict

WINDOW_DAYS = 28
MIN_AFTER_DAYS = 7
_READ_PURPOSES = ("search", "user", "agent")
_SEARCH_SOURCES = ("gsc", "bing")
_SEARCH_METRICS = ("impressions", "citations")


def page_path(url: str) -> str:
    """'/pricing' from 'https://www.acme.com/pricing/?x=1' or '/pricing/'."""
    u = (url or "").strip()
    if not u:
        return ""
    path = urlparse(u).path if "://" in u else u.split("?")[0].split("#")[0]
    path = "/" + path.strip("/")
    return path


def _windows(shipped: date, today: date, days: int) -> tuple[date, date, date, int]:
    """(before_start, after_start, after_end_exclusive, length): equal-length
    windows either side of the ship day; the ship day itself is excluded."""
    after_start = shipped + timedelta(days=1)
    length = max(0, min(days, (today - after_start).days + 1))
    after_end = after_start + timedelta(days=length)
    return shipped - timedelta(days=length), after_start, after_end, length


def _rate(k: int, n: int) -> float | None:
    return round(100.0 * k / n, 1) if n else None


def _pct_change(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return round(100.0 * (after - before) / before, 1)


def _count_signal(label: str, cells: dict[str, dict[str, float]], target: str,
                  w: tuple[date, date, date, int], source_note: str) -> dict[str, Any]:
    """Daily totals for `target` vs every other key in `cells` (key -> date -> value)."""
    b0, a0, a1, _ = w

    def total(keys: list[str], lo: date, hi: date) -> float:
        lo_s, hi_s = lo.isoformat(), hi.isoformat()
        return sum(v for k in keys for d, v in cells.get(k, {}).items() if lo_s <= d < hi_s)

    others = [k for k in cells if k != target]
    before, after = total([target], b0, a0), total([target], a0, a1)
    cb, ca = total(others, b0, a0), total(others, a0, a1)
    change, control = _pct_change(before, after), _pct_change(cb, ca)
    if target not in cells or before + after == 0:
        verdict = "no data"
    elif change is None:
        verdict = "no baseline" if after > 0 else "no data"
    elif control is not None and change - control >= 20:
        verdict = "up vs control"
    elif control is not None and change - control <= -20:
        verdict = "down vs control"
    else:
        verdict = "in line with control"
    return {"key": label.lower().replace(" ", "_"), "label": label, "kind": "count",
            "before": round(before, 1), "after": round(after, 1), "change_pct": change,
            "control_change_pct": control, "verdict": verdict, "note": source_note}


def intervention_proof(session: Session, tenant_id: int, days: int = WINDOW_DAYS,
                       today: date | None = None) -> dict[str, Any]:
    from api.dashboards_service import _branded_query_texts

    today = today or datetime.now(UTC).date()
    ledger = session.exec(
        select(Intervention).where(Intervention.tenant_id == tenant_id)
        .order_by(col(Intervention.shipped_at).desc())
    ).all()
    if not ledger:
        return {"items": [], "window_days": days, "summary": None}

    # Mentions: one pass over measured answers, bucketed by query and day.
    earliest = min(i.shipped_at for i in ledger).date() - timedelta(days=days + 1)
    rows = session.execute(
        sa_select(col(Result.id), col(Result.query_text), col(Result.created_at)).where(
            col(Result.tenant_id) == tenant_id,
            col(Result.status) == ResultStatus.ok,
            col(Result.variant) == ResultVariant.search,
            col(Result.created_at) >= datetime(earliest.year, earliest.month, earliest.day,
                                               tzinfo=UTC),
        )
    ).all()
    named = set(session.execute(
        sa_select(col(Mention.result_id)).join(Result, col(Result.id) == col(Mention.result_id))
        .where(col(Result.tenant_id) == tenant_id, col(Mention.entity_type) == "brand",
               col(Result.created_at) >= datetime(earliest.year, earliest.month, earliest.day,
                                                  tzinfo=UTC))
    ).scalars().all())
    by_query: dict[str, list[tuple[date, bool]]] = defaultdict(list)
    for rid, q, created in rows:
        by_query[q].append((created.date(), rid in named))
    treated = {i.query_text for i in ledger}
    controls = set(by_query) - treated - _branded_query_texts(session, tenant_id)

    # Page-level counts, keyed by path then date.
    reads: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for path, d, hits in session.execute(
        sa_select(col(AgentTrafficDaily.path), col(AgentTrafficDaily.date),
                  col(AgentTrafficDaily.hits)).where(
            col(AgentTrafficDaily.tenant_id) == tenant_id,
            col(AgentTrafficDaily.purpose).in_(_READ_PURPOSES),
        )
    ).all():
        reads[page_path(path)][d] += hits
    search: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for page, d, value in session.execute(
        sa_select(col(FirstPartyDaily.page), col(FirstPartyDaily.date),
                  col(FirstPartyDaily.value)).where(
            col(FirstPartyDaily.tenant_id) == tenant_id,
            col(FirstPartyDaily.source).in_(_SEARCH_SOURCES),
            col(FirstPartyDaily.metric).in_(_SEARCH_METRICS),
            col(FirstPartyDaily.page) != "", col(FirstPartyDaily.date) != "",
        )
    ).all():
        search[page_path(page)][d] += value
    referrals: dict[str, float] = defaultdict(float)
    for d, n in session.execute(
        sa_select(col(AiReferralDaily.date), col(AiReferralDaily.sessions))
        .where(col(AiReferralDaily.tenant_id) == tenant_id)
    ).all():
        referrals[d] += n

    items = []
    for item in ledger:
        shipped = item.shipped_at.date()
        w = _windows(shipped, today, days)
        b0, a0, a1, length = w

        def tally(queries: set[str], lo: date, hi: date) -> tuple[int, int]:
            k = n = 0
            for q in queries:
                for d, hit in by_query.get(q, ()):
                    if lo <= d < hi:
                        n += 1
                        k += hit
            return k, n

        kb, nb = tally({item.query_text}, b0, a0)
        ka, na = tally({item.query_text}, a0, a1)
        ckb, cnb = tally(controls, b0, a0)
        cka, cna = tally(controls, a0, a1)
        delta = round(100.0 * (ka / na - kb / nb), 1) if na and nb else None
        cdelta = round(100.0 * (cka / cna - ckb / cnb), 1) if cna and cnb else None
        test = change_verdict(kb, nb, ka, na)
        signals: list[dict[str, Any]] = [{
            "key": "mentions", "label": "Named in answers", "kind": "rate",
            "before": _rate(kb, nb), "after": _rate(ka, na), "before_n": nb, "after_n": na,
            "delta_pts": delta, "control_delta_pts": cdelta,
            "net_pts": round(delta - cdelta, 1) if delta is not None and cdelta is not None
            else None,
            "verdict": test["verdict"], "p_value": test["p_value"],
            "note": f"answers to “{item.query_text}” vs all untouched questions",
        }]
        path = page_path(item.url)
        if path:
            signals.append(_count_signal("AI bot reads", reads, path, w,
                                         f"{path} vs every other page, from your server logs"))
            signals.append(_count_signal("Search AI impressions", search, path, w,
                                         f"{path} vs every other page, from Search Console "
                                         "or Bing imports"))
        rb = sum(v for d, v in referrals.items() if b0.isoformat() <= d < a0.isoformat())
        ra = sum(v for d, v in referrals.items() if a0.isoformat() <= d < a1.isoformat())
        signals.append({
            "key": "referrals", "label": "AI referral sessions (sitewide)", "kind": "context",
            "before": rb, "after": ra, "change_pct": _pct_change(rb, ra),
            "verdict": "context only" if rb + ra else "no data",
            "note": "GA4, whole site: can't be tied to one fix",
        })

        if length < MIN_AFTER_DAYS:
            status = "awaiting"
            headline = (f"Shipped {shipped.isoformat()}: {length} of {MIN_AFTER_DAYS} days "
                        "measured so far. Check back after a week of runs.")
        elif test["verdict"] == "up" and (cdelta is None or delta is None or delta > cdelta):
            status = "proven"
            headline = (f"Named {delta:+} points on this question since the fix"
                        + (f", {round(delta - cdelta, 1):+} beyond the control"
                           if delta is not None and cdelta is not None else "") + ".")
        elif any(s.get("verdict") == "up vs control" for s in signals[1:]):
            status = "early"
            headline = "Page signals are up against the control; answers haven't moved yet."
        elif test["verdict"] == "down":
            status = "worse"
            headline = f"Named {delta:+} points on this question since the fix."
        elif nb == 0:
            status = "no_change"
            headline = ("No answers were measured on this question before the fix, so "
                        "there's no baseline. Page signals below still compare.")
        else:
            status = "no_change"
            headline = ("No change beyond the noise yet."
                        if test["verdict"] == "no real change"
                        else "Too few answers on this question to tell yet.")
        items.append({
            "id": item.id, "query": item.query_text, "description": item.description,
            "url": item.url, "path": path, "shipped_at": shipped.isoformat(),
            "window_days": length, "status": status, "headline": headline,
            "signals": signals,
        })

    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it["status"]] += 1
    measured = len(items) - counts["awaiting"]
    summary = (f"{counts['proven']} of {measured} measured fixes show a real lift in answers"
               + (f"; {counts['early']} more show early page signals" if counts["early"] else "")
               + "." if measured else "No fix has a full week of data after it yet.")
    return {"items": items, "window_days": days, "summary": summary, "counts": dict(counts)}
