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

An engine change inside a window (a model switch, a layout change: see
dashboards.overview.engine_breaks) moves answers on that engine for reasons
that have nothing to do with the fix. That engine's answers are kept only
from the state the fix shipped in, on both sides of the ship date; when
that removes most of the data or no lift remains, the fix is "confounded"
rather than proven.
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
from engine.analytics.ga4 import tracking_gaps
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


# Kinds of fix whose outcome is a page being cited, not the brand being named.
PAGE_PLAYS = frozenset({"refresh", "own_page", "broken_page"})
# The after-window is re-tested at each of these lengths: the first one where
# the change passes the test is how long the fix took to show.
HORIZONS = (7, 14, 21, 28)

_SIGNAL_LABEL = {"mentions": "Named in answers", "wrong_fact": "Stated wrong in answers",
                 "page_cited": "Answers citing the page"}


def metric_for(item: Intervention) -> tuple[str, int | None]:
    """What a fix is judged on, from the kind of recommendation it came from:
    a wrong fact on how often it is still stated wrong, a page fix on how
    often the page is cited, everything else on how often the subject (the
    brand, or a rival for a rival's change) is named."""
    if item.play == "accuracy" and item.gap_ref.startswith("accuracy:"):
        try:
            return "wrong_fact", int(item.gap_ref.split(":", 1)[1])
        except ValueError:
            pass
    if item.play in PAGE_PLAYS and not item.subject and page_path(item.url):
        return "page_cited", None
    return "mentions", None


def _scope_of(item: Intervention) -> tuple[set[str], set[str]]:
    questions = set(item.questions or ([item.query_text] if item.query_text else []))
    return questions, set(item.families or [])


def intervention_proof(session: Session, tenant_id: int, days: int = WINDOW_DAYS,
                       today: date | None = None) -> dict[str, Any]:
    """Every logged or detected fix, measured the same way: equal windows
    either side of the ship date on the answers the fix was for, against a
    control where one exists (the untouched questions, or the other engines
    for an engine-wide fix), with engine changes trimmed out."""
    from api.dashboards.common import _off_score_query_texts, _owned_domains
    from api.dashboards.overview import engine_breaks
    from api.engine_weights import FAMILY_LABELS, family_of
    from api.models import AccuracyFinding, Citation, PageChange
    from engine.processing.citations import domain_is_owned

    today = today or datetime.now(UTC).date()
    ledger = session.exec(
        select(Intervention).where(Intervention.tenant_id == tenant_id)
        .order_by(col(Intervention.shipped_at).desc())
    ).all()
    if not ledger:
        return {"items": [], "rival_items": [], "window_days": days, "summary": None}

    # One pass over measured answers, bucketed by query.
    earliest = min(i.shipped_at for i in ledger).date() - timedelta(days=days + 1)
    since = datetime(earliest.year, earliest.month, earliest.day, tzinfo=UTC)
    rows = session.execute(
        sa_select(col(Result.id), col(Result.query_text), col(Result.created_at),
                  col(Result.surface)).where(
            col(Result.tenant_id) == tenant_id,
            col(Result.status) == ResultStatus.ok,
            col(Result.variant) == ResultVariant.search,
            col(Result.created_at) >= since,
        )
    ).all()
    named = set(session.execute(
        sa_select(col(Mention.result_id)).join(Result, col(Result.id) == col(Mention.result_id))
        .where(col(Result.tenant_id) == tenant_id, col(Mention.entity_type) == "brand",
               col(Result.created_at) >= since)
    ).scalars().all())
    by_query: dict[str, list[tuple[date, int, str]]] = defaultdict(list)
    for rid, q, created, surface in rows:
        by_query[q].append((created.date(), rid, str(surface)))

    metrics = {i.id: metric_for(i) for i in ledger}
    # Loaded only when a fix needs them: who else an answer names (a rival's
    # change), which answers state a fact wrong, which cite a brand page.
    subjects = {i.subject for i in ledger if i.subject}
    rivals_named: dict[int, set[str]] = defaultdict(set)
    if subjects:
        for rid, name in session.execute(
            sa_select(col(Mention.result_id), col(Mention.entity_name))
            .join(Result, col(Result.id) == col(Mention.result_id))
            .where(col(Result.tenant_id) == tenant_id, col(Mention.entity_type) != "brand",
                   col(Mention.entity_name).in_(sorted(subjects)),
                   col(Result.created_at) >= since)
        ).all():
            rivals_named[rid].add(name)
    fact_ids = sorted({f for m, f in metrics.values() if m == "wrong_fact" and f is not None})
    wrong: dict[int, set[int]] = defaultdict(set)
    if fact_ids:
        for fact_id, rid in session.execute(
            sa_select(col(AccuracyFinding.fact_id), col(AccuracyFinding.result_id)).where(
                col(AccuracyFinding.tenant_id) == tenant_id,
                col(AccuracyFinding.fact_id).in_(fact_ids))
        ).all():
            wrong[fact_id].add(rid)
    cited_paths: dict[int, set[str]] = defaultdict(set)
    if any(m == "page_cited" for m, _f in metrics.values()):
        for rid, url in session.execute(
            sa_select(col(Citation.result_id), col(Citation.url))
            .join(Result, col(Result.id) == col(Citation.result_id))
            .where(col(Citation.tenant_id) == tenant_id,
                   col(Citation.source_category) == "brand",
                   col(Result.created_at) >= since)
        ).all():
            cited_paths[rid].add(page_path(url))

    competitive = set(by_query) - _off_score_query_texts(session, tenant_id)
    # Questions any of the brand's own fixes touched can't serve as a control.
    treated = {q for i in ledger if not i.subject for q in _scope_of(i)[0]}
    controls = competitive - treated
    owned = _owned_domains(session, tenant_id)
    # Engine changes anywhere in the ledger's span; filtered per window below.
    breaks = engine_breaks(session, tenant_id, earliest.isoformat(), today.isoformat())

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
    # What the crawl saw change on each fix's page.
    seen: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ch in session.exec(
        select(PageChange).where(PageChange.tenant_id == tenant_id,
                                 col(PageChange.intervention_id).in_(
                                     [i.id for i in ledger if i.id is not None]))
        .order_by(col(PageChange.detected_at))
    ).all():
        if ch.intervention_id is not None:
            seen[ch.intervention_id].append({
                "kind": ch.kind, "summary": ch.summary, "url": ch.url,
                "detected_at": ch.detected_at.date().isoformat()})

    items: list[dict[str, Any]] = []
    rival_items: list[dict[str, Any]] = []
    for item in ledger:
        shipped = item.shipped_at.date()
        w = _windows(shipped, today, days)
        b0, a0, a1, length = w
        metric, fact_id = metrics[item.id]
        lower_better = metric == "wrong_fact"
        good, bad = ("down", "up") if lower_better else ("up", "down")
        subject = item.subject
        questions, fams = _scope_of(item)
        path = page_path(item.url)

        if metric == "wrong_fact":
            hits = wrong.get(fact_id or 0, set())
        elif metric == "page_cited":
            hits = {rid for rid, paths in cited_paths.items() if path in paths}
        elif subject:
            hits = {rid for rid, names in rivals_named.items() if subject in names}
        else:
            hits = named
        if questions:
            treated_q = questions
        elif metric == "wrong_fact":
            treated_q = set(by_query)  # wherever the fact comes up
        else:
            treated_q = competitive
        # The control: the same measure where the fix wasn't. Untouched
        # questions for a fix aimed at questions; the other engines for a
        # fix aimed at an engine; none for a site-wide fix, and none for a
        # wrong fact or one page's citations (nothing else is comparable).
        control_q: set[str] = set()
        control_without: set[str] = set()
        versus = ""
        if metric == "mentions" and questions:
            control_q = (competitive - questions) if subject else (controls - questions)
            versus = "all untouched questions"
        elif metric == "mentions" and fams:
            control_q, control_without = treated_q, fams
            versus = "the other engines"

        # An engine that changed inside [before_start, after_end) can't tell
        # the fix from its own change. Its answers are kept only from the
        # regime the fix shipped in: from the last change before the ship
        # date up to the first change after it, on both sides, so before and
        # after compare the same engine state.
        confounding = [b for b in breaks if b0.isoformat() <= b["date"] < a1.isoformat()
                       and b["surface"] != "overall"]
        regime: dict[str, tuple[date, date]] = {}
        for b in confounding:
            lo, hi = regime.get(b["surface"], (b0, a1))
            when = date.fromisoformat(b["date"])
            if when <= shipped:
                lo = max(lo, when)
            else:
                hi = min(hi, when)
            regime[b["surface"]] = (lo, hi)

        def tally(queries: set[str], lo: date, hi: date, *,
                  only: set[str] | None = None, without: set[str] | None = None,
                  trim: dict[str, tuple[date, date]] = regime,
                  hit: set[int] = hits) -> tuple[int, int]:
            k = n = 0
            for q in queries:
                for d, rid, surface in by_query.get(q, ()):
                    if not lo <= d < hi:
                        continue
                    if surface in trim and not trim[surface][0] <= d < trim[surface][1]:
                        continue
                    fam = family_of(surface)
                    if (only and fam not in only) or (without and fam in without):
                        continue
                    n += 1
                    k += rid in hit
            return k, n

        only = fams or None
        kb, nb = tally(treated_q, b0, a0, only=only)
        ka, na = tally(treated_q, a0, a1, only=only)
        ckb, cnb = tally(control_q, b0, a0, only=only if not control_without else None,
                         without=control_without or None)
        cka, cna = tally(control_q, a0, a1, only=only if not control_without else None,
                         without=control_without or None)
        delta = round(100.0 * (ka / na - kb / nb), 1) if na and nb else None
        cdelta = round(100.0 * (cka / cna - ckb / cnb), 1) if cna and cnb else None
        test = change_verdict(kb, nb, ka, na)
        # The same test over every answer, to say whether a lift was there
        # before the trim, and how much data the engine changes cost.
        kb_all, nb_all = tally(treated_q, b0, a0, only=only, trim={})
        ka_all, na_all = tally(treated_q, a0, a1, only=only, trim={})
        test_all = change_verdict(kb_all, nb_all, ka_all, na_all)
        lost_most = bool(regime) and 2 * (nb + na) < nb_all + na_all
        left_out = ""
        if confounding:
            labels = ", ".join(sorted({b["label"] for b in confounding}))
            dates = ", ".join(sorted({b["date"] for b in confounding}))
            when = ("the engine state at the time of the change" if item.source == "detected"
                    else "the engine state the fix shipped in")
            left_out = f"{labels} answers limited to {when} (engine change on {dates})"

        # Per engine, and how long the change took to show.
        engine_fams = sorted({family_of(s) for q in treated_q for _d, _r, s in by_query.get(q, ())
                              if not fams or family_of(s) in fams})
        by_engine = []
        for fam in engine_fams:
            fkb, fnb = tally(treated_q, b0, a0, only={fam})
            fka, fna = tally(treated_q, a0, a1, only={fam})
            if not fnb + fna:
                continue
            by_engine.append({
                "family": fam, "label": FAMILY_LABELS.get(fam, fam),
                "before": _rate(fkb, fnb), "after": _rate(fka, fna),
                "before_n": fnb, "after_n": fna,
                "delta_pts": (round(100.0 * (fka / fna - fkb / fnb), 1) if fna and fnb
                              else None),
                "verdict": change_verdict(fkb, fnb, fka, fna)["verdict"],
            })
        days_to_effect: int | None = None
        for h in HORIZONS:
            if h > length:
                break
            hkb, hnb = tally(treated_q, a0 - timedelta(days=h + 1), a0, only=only)
            hka, hna = tally(treated_q, a0, a0 + timedelta(days=h), only=only)
            if change_verdict(hkb, hnb, hka, hna)["verdict"] == good:
                days_to_effect = h
                break

        one = next(iter(questions)) if len(questions) == 1 else ""
        if one:
            what, where = f"answers to “{one}”", "on this question"
        elif questions:
            what = f"answers to {len(questions)} questions"
            where = f"on these {len(questions)} questions"
        elif fams:
            engines = ", ".join(FAMILY_LABELS.get(f, f) for f in sorted(fams))
            what, where = f"answers on {engines}", f"on {engines}"
        else:
            what, where = "all answers", "across your questions"
        label = f"{subject} named in answers" if subject else _SIGNAL_LABEL[metric]
        signals: list[dict[str, Any]] = [{
            "key": metric, "label": label, "kind": "rate",
            "before": _rate(kb, nb), "after": _rate(ka, na), "before_n": nb, "after_n": na,
            "delta_pts": delta, "control_delta_pts": cdelta,
            "net_pts": round(delta - cdelta, 1) if delta is not None and cdelta is not None
            else None,
            "verdict": test["verdict"], "p_value": test["p_value"],
            "lower_is_better": lower_better,
            "note": (f"{what} vs {versus}" if versus else f"{what}, before and after")
                    + (f"; {left_out}" if left_out else ""),
        }]
        if metric == "page_cited":
            # The page being cited is the fix's own measure; whether the
            # brand is named there is what it is for.
            mkb, mnb = tally(treated_q, b0, a0, only=only, hit=named)
            mka, mna = tally(treated_q, a0, a1, only=only, hit=named)
            signals.append({
                "key": "mentions", "label": _SIGNAL_LABEL["mentions"], "kind": "rate",
                "before": _rate(mkb, mnb), "after": _rate(mka, mna),
                "before_n": mnb, "after_n": mna,
                "delta_pts": (round(100.0 * (mka / mna - mkb / mnb), 1) if mna and mnb
                              else None),
                "control_delta_pts": None, "net_pts": None,
                "verdict": change_verdict(mkb, mnb, mka, mna)["verdict"], "p_value": None,
                "note": f"{what}, before and after",
            })
        host = (urlparse(item.url).hostname or "") if item.url else ""
        # Server-log and Search Console signals exist only for the brand's own
        # pages; a fix logged against someone else's page has none.
        if path and not subject and (not host or not owned or domain_is_owned(host, owned)):
            signals.append(_count_signal("AI bot reads", reads, path, w,
                                         f"{path} vs every other page, from your server logs"))
            signals.append(_count_signal("Search AI impressions", search, path, w,
                                         f"{path} vs every other page, from Search Console "
                                         "or Bing imports"))
        if not subject:
            rb = sum(v for d, v in referrals.items() if b0.isoformat() <= d < a0.isoformat())
            ra = sum(v for d, v in referrals.items() if a0.isoformat() <= d < a1.isoformat())
            gaps = tracking_gaps(b0.isoformat(), (a1 - timedelta(days=1)).isoformat())
            signals.append({
                "key": "referrals", "label": "AI referral sessions (sitewide)",
                "kind": "context",
                "before": rb, "after": ra, "change_pct": _pct_change(rb, ra),
                "verdict": "context only" if rb + ra else "no data",
                "note": "GA4, whole site: can't be tied to one fix"
                        + "".join(f". Undercounts {g['engine']} for {g['label']}: its links "
                                  "went untagged, so those visits show as Direct" for g in gaps),
            })

        who = f"{subject}'s mention rate" if subject else "Mention rate"
        event = "the change" if item.source == "detected" else "the fix"
        better = (delta is not None and cdelta is not None
                  and (delta < cdelta if lower_better else delta > cdelta))
        if length < MIN_AFTER_DAYS:
            status = "awaiting"
            headline = (f"Shipped {shipped.isoformat()}: {length} of {MIN_AFTER_DAYS} days "
                        "measured so far. Check back after a week of runs.")
        elif confounding and (lost_most or test["verdict"] != good):
            status = "confounded"
            b = confounding[0]
            headline = (f"An engine change on {b['date']} ({b['label']}) overlaps this "
                        "window, so "
                        + ("the lift" if test_all["verdict"] == good else "any lift")
                        + f" can't be attributed to {event}. " + b["note"])
        elif test["verdict"] == good and (cdelta is None or delta is None or better):
            status = "proven"
            if metric == "wrong_fact":
                headline = (f"Answers stating this wrong fell from {_rate(kb, nb)}% to "
                            f"{_rate(ka, na)}% since {event}.")
            elif metric == "page_cited":
                headline = (f"Answers citing this page rose from {_rate(kb, nb)}% to "
                            f"{_rate(ka, na)}% {where} since {event}.")
            else:
                headline = (f"{who} {where} is up {delta} points since {event}"
                            + (f", {round(delta - cdelta, 1)} more than the control"
                               if delta is not None and cdelta is not None else "") + ".")
            if left_out:
                headline += f" {left_out[0].upper()}{left_out[1:]}."
        elif any(s.get("verdict") == "up vs control" for s in signals[1:]):
            status = "early"
            headline = "Page signals are up against the control; answers haven't moved yet."
        elif test["verdict"] == bad:
            status = "worse"
            if metric == "wrong_fact":
                headline = (f"Answers stating this wrong rose from {_rate(kb, nb)}% to "
                            f"{_rate(ka, na)}% since {event}.")
            elif metric == "page_cited":
                headline = (f"Answers citing this page fell from {_rate(kb, nb)}% to "
                            f"{_rate(ka, na)}% {where} since {event}.")
            else:
                headline = (f"{who} {where} is down {abs(delta or 0)} points "
                            f"since {event}.")
        elif nb == 0:
            status = "no_change"
            headline = (f"No answers were measured {where} before {event}, so "
                        "there's no baseline. Page signals below still compare.")
        else:
            status = "no_change"
            headline = ("No change beyond the noise yet."
                        if test["verdict"] == "no real change"
                        else f"Too few answers {where} to tell yet.")
        predicted = item.predicted or {}
        entry = {
            "id": item.id, "query": item.query_text, "description": item.description,
            "url": item.url, "path": path, "shipped_at": shipped.isoformat(),
            "window_days": length, "status": status, "headline": headline,
            "signals": signals, "breaks": confounding,
            # The experiment: where it came from, what it was, what it predicted.
            "source": item.source or "logged", "subject": subject, "metric": metric,
            "play": item.play, "category": item.category, "control": item.control,
            "evidence": item.evidence, "recommendation_id": item.recommendation_id,
            "predicted": ({"band": predicted.get("band", ""), "score": predicted.get("score"),
                           "basis": predicted.get("basis", "")} if predicted else None),
            "questions": sorted(questions), "families": sorted(fams),
            "by_engine": by_engine, "days_to_effect": days_to_effect,
            "changes": seen.get(item.id or 0, []),
        }
        (rival_items if subject else items).append(entry)

    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it["status"]] += 1
    measured = len(items) - counts["awaiting"]
    summary = None
    if items:
        summary = (f"{counts['proven']} of {measured} measured fixes show a real lift in answers"
                   + (f"; {counts['early']} more show early page signals"
                      if counts["early"] else "")
                   + (f"; {counts['confounded']} can't be read because an engine changed in the "
                      "window" if counts["confounded"] else "")
                   + "." if measured else "No fix has a full week of data after it yet.")
    return {"items": items, "rival_items": rival_items, "window_days": days,
            "summary": summary, "counts": dict(counts)}


def refresh_outcomes(session: Session, tenant_id: int, today: date | None = None) -> int:
    """Store what each fix did (FixOutcome), one row per fix. Rows are
    refreshed after every run until the after-window is full, then left
    alone: a final outcome doesn't move when the questions or engines later
    do. Returns the number of rows written. Does not commit."""
    from api.models import FixOutcome, utcnow

    proof = intervention_proof(session, tenant_id, today=today)
    entries = [*proof["items"], *proof["rival_items"]]
    if not entries:
        return 0
    existing = {
        o.intervention_id: o
        for o in session.exec(select(FixOutcome).where(FixOutcome.tenant_id == tenant_id)).all()
    }
    written = 0
    for it in entries:
        row = existing.get(it["id"])
        if row is not None and row.final:
            continue
        if row is None:
            row = FixOutcome(tenant_id=tenant_id, intervention_id=it["id"])
        primary = it["signals"][0]
        row.status, row.metric = it["status"], it["metric"]
        row.before_rate, row.after_rate = primary["before"], primary["after"]
        row.n_before, row.n_after = primary["before_n"], primary["after_n"]
        row.delta_pts = primary["delta_pts"]
        row.control_delta_pts = primary["control_delta_pts"]
        row.net_pts = primary["net_pts"]
        row.verdict, row.p_value = primary["verdict"], primary["p_value"]
        row.days_to_effect = it["days_to_effect"]
        row.window_days = it["window_days"]
        row.by_engine = it["by_engine"]
        row.signals = it["signals"]
        row.final = it["window_days"] >= WINDOW_DAYS
        row.measured_at = utcnow()
        session.add(row)
        written += 1
    session.flush()
    return written
