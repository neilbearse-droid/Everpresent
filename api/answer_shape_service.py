"""Answer Shape (m33): how AI answers are built and how that is changing,
so a model release that changes citing behaviour shows up as a dated,
explained break instead of a mystery dip.

- shape per engine and served model: search rate, citations and inline links
  per answer, own-site / third-party / rival share of what's cited, brand
  mention rate, and mentions that came with no link to the brand's own site
- model timeline: when each engine started serving a new model
- memory vs search: brand mention rate in answers given without web search
  (what the model "believes") against answers with search, with 95% ranges
- themes and objections: what engines say around the brand's name, from the
  stored mention sentences (deterministic lexicon, no LLM spend)
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.models import Citation, Mention, Result, ResultStatus, ResultVariant
from engine.processing.stats import rate_summary

WINDOW_DAYS = 60
# Surfaces whose measurement call forces web search: their unforced "natural"
# probe is the only honest read of whether the engine would search.
_FORCED = {"openai_api", "perplexity_api"}
_SERP = {"google_aio", "google_ai_mode"}
_WEB = {"chatgpt_web", "perplexity_web", "copilot_web"}

# What answers talk about when they mention a brand, and words that turn a
# sentence into an objection. Category-neutral; tuned on hosting/domains/
# website-builder and SaaS answers.
THEMES: dict[str, tuple[str, ...]] = {
    "Price": ("price", "pricing", "cost", "cheap", "afford", "expensive", "$", "fee"),
    "Renewals": ("renewal", "renew", "first year", "introductory", "promo"),
    "Upsells": ("upsell", "add-on", "add on", "extras", "checkout"),
    "Support": ("support", "customer service", "help desk", "24/7"),
    "Ease of use": ("easy", "beginner", "intuitive", "simple", "drag-and-drop", "user-friendly"),
    "Features": ("feature", "tools", "integrat", "template", "ecommerce", "e-commerce"),
    "Performance": ("speed", "fast", "slow", "uptime", "performance", "reliab", "outage"),
    "Security": ("security", "ssl", "privacy", "protect", "malware"),
    "AI tools": ("ai ", "ai-", "airo", "generat", "assistant"),
    "Reputation": ("reputation", "review", "trust", "complain", "rated", "popular"),
}
_NEGATIVE = (
    "expensive", "pricey", "overpriced", "upsell", "hidden", "complain", "slow", "poor",
    "limited", "lacks", "lacking", "downside", "drawback", "however", " but ", "criticiz",
    "frustrat", "issue", "problem", "outage", "worse", "aggressive", "confusing", "steep",
    "higher renewal", "jumps", "increase",
)
_SENT = re.compile(r"[^.!?\n]+[.!?]?")


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _surface_label(s: str) -> str:
    from api.dashboards_service import _surface_label as label

    return label(s)


def answer_shape(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> dict[str, Any]:
    from api.dashboards_service import _branded_query_texts

    since = _since(days)
    branded = _branded_query_texts(session, tenant_id)
    conds: list[Any] = [
        Result.tenant_id == tenant_id,
        Result.status == ResultStatus.ok,
        col(Result.created_at) >= since,
    ]
    if branded:
        conds.append(col(Result.query_text).not_in(branded))
    rows = session.execute(
        sa_select(col(Result.id), col(Result.surface), col(Result.variant),
               col(Result.served_model), col(Result.web_search_calls),
               col(Result.logged_in), col(Result.created_at))
        .where(*conds).order_by(col(Result.created_at))
    ).all()
    if not rows:
        return {"has_data": False, "days": days}

    # Joined rather than IN (ids): a busy tenant has tens of thousands of
    # answers in the window, past the database's bound-parameter limits.
    brand_ids: set[int] = set(session.exec(
        select(col(Mention.result_id))
        .join(Result, col(Result.id) == col(Mention.result_id))
        .where(*conds, Mention.entity_type == "brand")
    ).all())
    cites: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for rid, cat, kind in session.exec(
        select(col(Citation.result_id), col(Citation.source_category), col(Citation.link_kind))
        .join(Result, col(Result.id) == col(Citation.result_id))
        .where(*conds)
    ).all():
        cites[rid].append((cat or "", kind or ""))

    # Per (surface, model): search-variant answers carry the shape; natural
    # probes carry "would it search on its own" for forced-search surfaces.
    shape: dict[tuple[str, str], dict[str, Any]] = {}
    timeline: dict[str, list[dict]] = defaultdict(list)
    natural: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # searched, total
    for rid, surface, variant, model, searches, logged_in, created in rows:
        surface = str(surface)
        model = model or ""
        if variant == ResultVariant.natural:
            natural[surface][0] += 1 if searches > 0 else 0
            natural[surface][1] += 1
        if variant != ResultVariant.search:
            continue
        day = created.date().isoformat()
        if model:
            tl = timeline[surface]
            if not tl or tl[-1]["model"] != model:
                tl.append({"model": model, "since": day})
        e = shape.setdefault((surface, model), {
            "surface": surface, "label": _surface_label(surface), "model": model,
            "answers": 0, "searched": 0, "citations": 0, "inline": 0, "own": 0,
            "third_party": 0, "rival": 0, "mentioned": 0, "mentioned_unlinked": 0,
            "logged_in": logged_in, "first_seen": day, "last_seen": day,
        })
        e["answers"] += 1
        e["last_seen"] = day
        cs = cites.get(rid, [])
        searched = (surface in _SERP or bool(cs)) if surface not in _FORCED else searches > 0
        e["searched"] += 1 if (searches > 0 or searched) else 0
        e["citations"] += len(cs)
        e["inline"] += sum(1 for _c, k in cs if k == "inline")
        e["own"] += sum(1 for c, _k in cs if c == "brand")
        e["rival"] += sum(1 for c, _k in cs if c == "competitor")
        e["third_party"] += sum(1 for c, _k in cs if c not in ("brand", "competitor"))
        if rid in brand_ids:
            e["mentioned"] += 1
            if not any(c == "brand" for c, _k in cs):
                e["mentioned_unlinked"] += 1

    engines = []
    for e in shape.values():
        n = e["answers"]
        c = e["citations"] or 0
        nat = natural.get(e["surface"])
        engines.append({
            **{k: e[k] for k in ("surface", "label", "model", "answers", "logged_in",
                                 "first_seen", "last_seen")},
            # For forced-search surfaces the honest search rate is the
            # unforced probe's, per surface (probes aren't split by model).
            "search_rate": round(100 * nat[0] / nat[1], 1) if (e["surface"] in _FORCED and nat
                                                                and nat[1]) else
            (round(100 * e["searched"] / n, 1) if n else 0.0),
            "search_rate_source": "unforced probe" if e["surface"] in _FORCED else "observed",
            "citations_per_answer": round(c / n, 2) if n else 0.0,
            "inline_share": round(100 * e["inline"] / c, 1) if c else 0.0,
            "own_share": round(100 * e["own"] / c, 1) if c else 0.0,
            "third_party_share": round(100 * e["third_party"] / c, 1) if c else 0.0,
            "rival_share": round(100 * e["rival"] / c, 1) if c else 0.0,
            "mention": rate_summary(e["mentioned"], n),
            "mentioned_unlinked_share": (round(100 * e["mentioned_unlinked"] / e["mentioned"], 1)
                                         if e["mentioned"] else 0.0),
            "model_note": "" if e["model"] else (
                "not shown by the interface" if e["surface"] in _SERP | _WEB
                else "not recorded (runs before Oct 2026)"),
        })
    engines.sort(key=lambda x: (x["label"], x["first_seen"]))
    changes = [
        {"surface": s, "label": _surface_label(s), "model": t["model"], "since": t["since"]}
        for s, tl in timeline.items() for t in tl[1:]  # the first entry isn't a change
    ]
    changes.sort(key=lambda c: c["since"], reverse=True)
    return {
        "has_data": True,
        "days": days,
        "engines": engines,
        "model_changes": changes,
        "current_models": {_surface_label(s): tl[-1]["model"]
                           for s, tl in timeline.items() if tl},
        "memory_vs_search": _memory_vs_search(rows, brand_ids),
        "perception": _perception(session, tenant_id, conds, rows),
    }


def _memory_vs_search(rows: Sequence[Any], brand_ids: set[int]) -> list[dict]:
    """Brand mention rate without search (memory) vs with search, per engine.
    The no-search twin plus natural probes that chose not to search are the
    memory sample; search-variant answers are the search sample."""
    mem: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    srch: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for rid, surface, variant, _model, searches, _li, _c in rows:
        s = str(surface)
        hit = 1 if rid in brand_ids else 0
        if variant == ResultVariant.nosearch or (variant == ResultVariant.natural
                                                 and searches == 0):
            mem[s][0] += hit
            mem[s][1] += 1
        elif variant == ResultVariant.search:
            srch[s][0] += hit
            srch[s][1] += 1
    out = []
    for s in sorted(set(mem) | set(srch), key=_surface_label):
        m, r = mem.get(s, [0, 0]), srch.get(s, [0, 0])
        if not m[1] and not r[1]:
            continue
        mem_rate = rate_summary(m[0], m[1]) if m[1] else None
        srch_rate = rate_summary(r[0], r[1]) if r[1] else None
        verdict = "needs data"
        if mem_rate and srch_rate and m[1] >= 10 and r[1] >= 10:
            if mem_rate["low"] > srch_rate["high"]:
                verdict = "known, but losing in search"
            elif srch_rate["low"] > mem_rate["high"]:
                verdict = "found by search, not yet known"
            else:
                verdict = "consistent"
        out.append({"surface": s, "label": _surface_label(s), "memory": mem_rate,
                    "search": srch_rate, "verdict": verdict})
    return out


def _perception(
    session: Session, tenant_id: int, conds: list[Any], rows: Sequence[Any]
) -> dict[str, Any]:
    """Themes around the brand's name and the objections engines raise, split
    by memory vs search answers. From stored mention sentences only."""
    from api.models import BrandProfile

    kind = {r[0]: ("memory" if r[2] == ResultVariant.nosearch or (
        r[2] == ResultVariant.natural and r[4] == 0) else "search") for r in rows}
    # A stored mention snippet spans neighbouring sentences about other
    # brands; only sentences that name this brand count toward its themes.
    profile = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    names = [n for n in ([profile.brand_name, *profile.aliases] if profile else []) if n]
    name_re = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b",
                         re.IGNORECASE) if names else None
    themes: dict[str, dict[str, Any]] = {
        t: {"theme": t, "mentions": 0, "objections": 0, "memory": 0, "search": 0,
            "examples": []} for t in THEMES
    }
    sentences = 0
    for rid, snippet in session.exec(
        select(col(Mention.result_id), col(Mention.context_snippet))
        .join(Result, col(Result.id) == col(Mention.result_id))
        .where(*conds, Mention.entity_type == "brand")
    ).all():
        for sent in _SENT.findall(snippet or ""):
            if name_re is not None and not name_re.search(sent):
                continue
            low = f" {sent.lower()} "
            sentences += 1
            neg = any(w in low for w in _NEGATIVE)
            for theme, words in THEMES.items():
                if any(w in low for w in words):
                    t = themes[theme]
                    t["mentions"] += 1
                    t[kind.get(rid, "search")] += 1
                    if neg:
                        t["objections"] += 1
                        if len(t["examples"]) < 3 and sent.strip() not in t["examples"]:
                            t["examples"].append(sent.strip()[:240])
    ranked = sorted((t for t in themes.values() if t["mentions"]),
                    key=lambda t: (-t["objections"], -t["mentions"], t["theme"]))
    return {"sentences": sentences, "themes": ranked}


def model_timeline(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> list[dict]:
    """Just the observed model changes, cheaply (one narrow query)."""
    timeline: dict[str, list[dict]] = defaultdict(list)
    for surface, model, created in session.exec(
        select(col(Result.surface), col(Result.served_model), col(Result.created_at))
        .where(Result.tenant_id == tenant_id, Result.variant == ResultVariant.search,
               Result.status == ResultStatus.ok, col(Result.created_at) >= _since(days),
               col(Result.served_model) != "")
        .order_by(col(Result.created_at))
    ).all():
        tl = timeline[str(surface)]
        if not tl or tl[-1]["model"] != model:
            tl.append({"model": model, "since": created.date().isoformat()})
    return [
        {"surface": s, "label": _surface_label(s), "model": t["model"], "since": t["since"]}
        for s, tl in timeline.items() for t in tl[1:]
    ]
