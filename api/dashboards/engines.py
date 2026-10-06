"""Engines: per-engine scorecard, routing (how each engine finds you), engine modes."""

from collections import defaultdict

from sqlmodel import Session, col, select

from api.dashboards.common import (
    AGENT_CORPUS_TAGS,
    _brand_and_cited_ids,
    _brand_name,
    _clean_date,
    _date_in_range,
    _date_window,
    _latest_results_by_variant,
    _mean,
    _pct,
    _surface_label,
)
from api.models import (
    Citation,
    Mention,
    Query,
    Result,
    ResultVariant,
    VisibilityDaily,
)

# The "why you're absent" diagnosis, derived from the search vs training-only
# (nosearch) diff. Fixes are prescriptive and vendor-neutral.
_DIAGNOSIS = {
    "visible": {
        "label": "Visible",
        "fix": "You appear in the answer users see. Protect it: keep the cited content fresh.",
    },
    "content_gap": {
        "label": "Content gap",
        "fix": (
            "The AIs know your brand, but when they search the live web they surface "
            "competitors instead. Publish citable, up-to-date content that answers this "
            "query directly — this is a GEO/SEO content problem, not an awareness one."
        ),
    },
    "knowledge_gap": {
        "label": "Knowledge gap",
        "fix": (
            "The AIs neither recall your brand from training nor find you when they "
            "search. You need both: authoritative published content AND broader brand "
            "presence across the web so future model training picks you up."
        ),
    },
    "undetermined": {
        "label": "Absent",
        "fix": (
            "Absent from the answer. Enable an engine with a training baseline "
            "(ChatGPT, Claude, or Gemini) to diagnose whether this is a content or a "
            "knowledge gap."
        ),
    },
}


def engine_scorecard(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Cross-engine analysis: per-engine visibility, a query×engine grid of who
    appears (you / competitor / absent), and a per-query 'why you're missing'
    diagnosis from the search-vs-training diff. Pure reads — no LLM, no spend."""
    brand_name = _brand_name(session, tenant_id)
    # The competitive matrix: branded queries live on the Brand tab, agent
    # prompts under Agent picks.
    queries = [
        q
        for q in session.exec(select(Query).where(Query.tenant_id == tenant_id)).all()
        if not q.branded and q.corpus_tag not in AGENT_CORPUS_TAGS
    ]

    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    nosearch = _latest_results_by_variant(
        session, tenant_id, ResultVariant.nosearch, lo, hi, scope="competitive"
    )

    # Mentions per result: brand present? which competitors?
    all_ids = [r.id for r in list(search.values()) + list(nosearch.values()) if r.id is not None]
    brand_ids: set[int] = set()
    competitors_by_result: dict[int, set[str]] = defaultdict(set)
    if all_ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(all_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            if m.entity_type == "brand":
                brand_ids.add(m.result_id)
            else:
                competitors_by_result[m.result_id].add(m.entity_name)

    # Include surfaces that produced a nosearch (training-twin) result even if
    # their search variant failed (§audit H5) — otherwise the diagnosis can't
    # see "known from training but not surfaced" and mislabels content_gap as
    # knowledge_gap/undetermined.
    surfaces = sorted({s for (_, s) in search} | {s for (_, s) in nosearch})

    # Brand-cited result ids (§AEO-plan m3): a citation to a brand-owned page,
    # distinct from a brand *mention*. Mentions and citations move
    # independently — you can be named without being linked, and vice versa.
    search_ids = [r.id for r in search.values() if r.id is not None]
    brand_cited_ids: set[int] = set()
    if search_ids:
        for c in session.exec(
            select(Citation).where(
                Citation.result_id.in_(search_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Citation.source_category == "brand",
            )
        ).all():
            brand_cited_ids.add(c.result_id)

    # Per-engine rollup.
    engines = []
    for surface in surfaces:
        measured = brand = comp = cited = 0
        comp_tally: dict[str, int] = defaultdict(int)
        for (_qtext, s), result in search.items():
            if s != surface:
                continue
            measured += 1
            if result.id in brand_ids:
                brand += 1
            if result.id in brand_cited_ids:
                cited += 1
            comps = competitors_by_result.get(result.id or -1, set())
            if comps:
                comp += 1
            for name in comps:
                comp_tally[name] += 1
        top_comp = max(comp_tally, key=lambda n: comp_tally[n]) if comp_tally else None
        brand_rate = round(100.0 * brand / measured, 1) if measured else 0.0
        citation_rate = round(100.0 * cited / measured, 1) if measured else 0.0
        engines.append({
            "surface": surface,
            "queries_measured": measured,
            "brand_present": brand,
            "brand_rate": brand_rate,
            "brand_cited": cited,
            "citation_rate": citation_rate,
            # Named but not linked: the gap the report says to watch per engine.
            "mention_citation_gap": round(brand_rate - citation_rate, 1),
            "competitor_present": comp,
            "top_competitor": top_comp,
        })

    # Per-query matrix + diagnosis.
    matrix = []
    summary: dict[str, int] = defaultdict(int)
    for query in sorted(queries, key=lambda q: (q.corpus_tag, q.text)):
        # A retired (inactive) query with nothing measured in this window
        # isn't part of the current picture.
        if not query.active and not any(
            (query.text, sf) in search or (query.text, sf) in nosearch for sf in surfaces
        ):
            continue
        cells: dict[str, dict] = {}
        brand_in_search = brand_in_nosearch = has_nosearch = False
        for surface in surfaces:
            # Check the training twin FIRST, so a surface whose search variant
            # failed but whose nosearch succeeded still informs the diagnosis
            # (§audit H5).
            ns = nosearch.get((query.text, surface))
            if ns is not None:
                has_nosearch = True
                if ns.id in brand_ids:
                    brand_in_nosearch = True
            result = search.get((query.text, surface))
            if result is None:
                continue
            comps = sorted(competitors_by_result.get(result.id or -1, set()))
            if result.id in brand_ids:
                state = "brand"
                brand_in_search = True
            elif comps:
                state = "competitor"
            else:
                state = "absent"
            cells[surface] = {"state": state, "competitors": comps}

        if brand_in_search:
            dtype = "visible"
        elif not has_nosearch:
            dtype = "undetermined"
        elif brand_in_nosearch:
            dtype = "content_gap"
        else:
            dtype = "knowledge_gap"
        summary[dtype] += 1
        matrix.append({
            "id": query.id,
            "query": query.text,
            "corpus_tag": query.corpus_tag,
            "cells": cells,
            "diagnosis": {"type": dtype, **_DIAGNOSIS[dtype]},
        })

    return {
        "brand_name": brand_name,
        "engines": engines,
        "matrix": matrix,
        "diagnosis_summary": dict(summary),
    }


# Surfaces whose search variant is FORCED (tool_choice), so their search-variant
# results can't reveal natural routing — only their M2 natural probe can. Kept
# in sync with worker.jobs.A_ADAPTERS[...].forces_search.
_FORCED_SEARCH_SURFACES = {"openai_api", "perplexity_api"}
# Google's AI answer surfaces are search features: always retrieval.
_SERP_SURFACES = {"google_aio", "google_ai_mode"}
# Consumer UIs captured in a browser: no search count, so a cited source is
# the evidence that the answer searched.
_BROWSER_SURFACES = {"chatgpt_web", "perplexity_web", "copilot_web", "gemini_web"}


def routing_report(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Search-routing map (§AEO-plan M2): per engine, the share of priority
    prompts that trigger live search vs. are answered from training. Retrieval
    optimization only pays off for prompts that actually search — this is the
    'step one' diagnostic. For forced surfaces the signal comes from the
    un-forced natural probe; for the rest, from their (already un-forced)
    search variant's observed search count."""
    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    natural = _latest_results_by_variant(
        session, tenant_id, ResultVariant.natural, lo, hi, scope="competitive"
    )

    per_surface: dict[str, dict] = defaultdict(lambda: {"measured": 0, "searched": 0})
    prompts: dict[str, dict[str, bool]] = defaultdict(dict)
    for qtext, surface in set(search) | set(natural):
        if surface in _FORCED_SEARCH_SURFACES:
            src = natural.get((qtext, surface))  # only probed queries have a signal
        else:
            src = search.get((qtext, surface))
        if src is None:
            continue
        searched = (src.web_search_calls or 0) > 0
        per_surface[surface]["measured"] += 1
        per_surface[surface]["searched"] += 1 if searched else 0
        prompts[qtext][surface] = searched

    engines = [
        {
            "surface": s,
            "measured": v["measured"],
            "searched": v["searched"],
            "search_rate": _pct(v["searched"], v["measured"]),
            "from_probe": s in _FORCED_SEARCH_SURFACES,
        }
        for s, v in sorted(per_surface.items())
    ]
    rows = [
        {"query": q, "engines": dict(sorted(d.items()))}
        for q, d in sorted(prompts.items())
    ]
    return {
        "brand_name": _brand_name(session, tenant_id),
        "engines": engines,
        "prompts": rows,
        "observed": any(e["measured"] for e in engines),
    }


# Retrieve-vs-recall banding by observed search propensity in the category.
# Deliberately wide dead-band in the middle so a genuinely split engine reads
# as "mixed" rather than being forced to one pole.
_RETRIEVE_AT = 66.0
_RECALL_AT = 33.0

_MODE_PLAY = {
    "retrieve": "Publish specific, well-structured pages that answer the sub-queries "
    "these engines search.",
    "recall": "Build mentions in widely read sources (press, directories, reference "
    "sites) so future model versions learn about you.",
    "mixed": "Combine both: citable pages for searched prompts, and broad coverage "
    "for prompts answered from memory.",
}


def engine_modes(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Reframed Overview (§AEO-plan M0): 'AI visibility' is not one number.
    Per engine, how it reaches answers in THIS category — retrieve vs recall by
    observed search propensity — and the brand's standing measured in the
    currency that matters for that mode (cited-in-live-answers for retrieval,
    named-from-memory for recall). Competitive scope only; branded probes live
    in the Brand layer. Pure reads."""
    lo, hi = _date_window(start, end)
    search = _latest_results_by_variant(
        session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
    )
    natural = _latest_results_by_variant(
        session, tenant_id, ResultVariant.natural, lo, hi, scope="competitive"
    )
    nosearch = _latest_results_by_variant(
        session, tenant_id, ResultVariant.nosearch, lo, hi, scope="competitive"
    )

    all_ids = [
        r.id
        for r in (*search.values(), *natural.values(), *nosearch.values())
        if r.id is not None
    ]
    brand_ids, cited_ids = _brand_and_cited_ids(session, all_ids)
    # Captured surfaces don't report a search count. Google's AI surfaces are
    # search features by definition; a browser-captured answer searched if it
    # shows sources. Without this they'd read as "answers from memory".
    captured_ids = [
        r.id for (_q, s), r in search.items()
        if s in _BROWSER_SURFACES and r.id is not None
    ]
    sourced_ids: set[int] = set()
    if captured_ids:
        sourced_ids = set(session.exec(
            select(col(Citation.result_id))
            .where(col(Citation.result_id).in_(captured_ids))
            .distinct()
        ).all())

    def _searched(r: Result) -> bool:
        surface = str(r.surface)
        if surface in _SERP_SURFACES:
            return True
        if surface in _BROWSER_SURFACES:
            return r.id in sourced_ids
        return (r.web_search_calls or 0) > 0

    surfaces = sorted({s for (_q, s) in search} | {s for (_q, s) in natural})
    engines = []
    for surface in surfaces:
        # A forced-search surface can't reveal natural routing from its search
        # variant — read its propensity + user-visible answer from the natural
        # probe. Every other surface's search variant is already un-forced.
        forced = surface in _FORCED_SEARCH_SURFACES
        signal = natural if forced else search
        sig_rows = [r for (q, s), r in signal.items() if s == surface]
        srch_rows = [r for (q, s), r in search.items() if s == surface]
        measured = len(sig_rows)
        if not measured:
            continue
        searched = sum(1 for r in sig_rows if _searched(r))
        named = sum(1 for r in sig_rows if r.id in brand_ids)
        search_rate = _pct(searched, measured)

        if search_rate >= _RETRIEVE_AT:
            mode = "retrieve"
        elif search_rate <= _RECALL_AT:
            mode = "recall"
        else:
            mode = "mixed"

        # Fan-out breadth (retrieval engines only expose it): mean sub-queries
        # over prompts that actually searched.
        fo_seen = [
            len(r.fanout_queries)
            for r in srch_rows
            if (r.web_search_calls or 0) > 0 and r.fanout_queries
        ]
        avg_fanout = round(sum(fo_seen) / len(fo_seen), 1) if fo_seen else None

        srch_measured = len(srch_rows)
        cited = sum(1 for r in srch_rows if r.id in cited_ids)
        named_rate = _pct(named, measured)
        cited_rate = _pct(cited, srch_measured)

        if mode == "retrieve":
            standing_value, standing_unit = cited_rate, "cited"
            standing_label = "cited in live answers"
        elif mode == "recall":
            standing_value, standing_unit = named_rate, "named"
            standing_label = "named from memory"
        else:
            standing_value, standing_unit = named_rate, "named"
            standing_label = "named in answers"

        if mode == "retrieve":
            blurb = f"Searches on {round(search_rate)}% of your category prompts"
            blurb += f", splitting each into about {avg_fanout} sub-queries." if avg_fanout else "."
        elif mode == "recall":
            blurb = (
                f"Answers {round(100 - search_rate)}% of your category prompts from "
                "memory, without searching."
            )
        else:
            blurb = (
                f"Searches on {round(search_rate)}% of your category prompts and answers "
                "the rest from memory."
            )

        engines.append({
            "surface": surface,
            "label": _surface_label(surface),
            "mode": mode,
            "search_rate": search_rate,
            "avg_fanout": avg_fanout,
            "measured": measured,
            "from_probe": forced,
            "standing_value": standing_value,
            "standing_unit": standing_unit,
            "standing_label": standing_label,
            "named_rate": named_rate,
            "cited_rate": cited_rate,
            "blurb": blurb,
            "play": _MODE_PLAY[mode],
        })

    engines.sort(key=lambda e: (-e["measured"], e["surface"]))

    # Two-mode split — the honest reframe. Recall visibility is measured over
    # the training twins (what the model knows without searching); retrieval
    # visibility over the answers where it actually searched.
    # Recall = answers given WITHOUT searching: the training twins, plus
    # natural probes that chose not to search, counted once per
    # (query, surface) (a probe that searched is retrieval, not memory).
    twin_rows = [r for r in nosearch.values() if r.id is not None]
    twin_rows += [
        r
        for key, r in natural.items()
        if r.id is not None and (r.web_search_calls or 0) == 0 and key not in nosearch
    ]
    twin_named = sum(1 for r in twin_rows if r.id in brand_ids)
    searched_rows = [
        r for r in search.values() if r.id is not None and (r.web_search_calls or 0) > 0
    ]
    searched_named = sum(1 for r in searched_rows if r.id in brand_ids)
    modes = {
        "recall": {
            "visibility": _pct(twin_named, len(twin_rows)),
            "answers": len(twin_rows),
        },
        "retrieval": {
            "visibility": _pct(searched_named, len(searched_rows)),
            "answers": len(searched_rows),
        },
    }

    # Composite — demoted to a blended roll-up, not the headline. Latest daily
    # brand score, the same figure the trend chart lands on.
    start, end = _clean_date(start), _clean_date(end)
    latest_daily = None
    daily = [
        r for r in session.exec(
            select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
        ).all()
        if _date_in_range(r.date, start, end)
    ]
    if daily:
        last_date = max(r.date for r in daily)
        scores = [r.brand_score for r in daily if r.date == last_date]
        if scores:
            latest_daily = {"score": round(_mean(scores), 1), "date": last_date}

    return {
        "brand_name": _brand_name(session, tenant_id),
        "engines": engines,
        "modes": modes,
        "composite": latest_daily,
        "observed": bool(engines),
    }
