"""Projected impact: the one scale every recommendation is ranked on.

    impact = reach x gap x odds

  reach  the audience-weighted share of the measured answers an issue touches
         (an answer on ChatGPT counts for more than one on a small engine, by
         the same weights as the headline: api.engine_weights)
  gap    how many of those answers leave the brand out, or carry the problem
  odds   how likely the fix is to change them: who controls it (the brand,
         someone the brand can ask, someone who has to choose the brand), how
         strong the evidence for the tactic is, and how directly it acts

Reach and gap are measured. Odds are a judgement: the weights live in the
tables below so they can be argued with and tuned in one place, and the
product shows them as words (control, evidence), never as a forecast. The
score orders the list and sets the band; it is not a promised lift.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import false
from sqlmodel import Session, col, select

from api.dashboards.common import _generic_only, _off_score_query_texts
from api.engine_weights import FAMILY_LABELS, engine_weights, family_of
from api.models import Mention, Query, Result, ResultStatus, ResultVariant, Tenant

WINDOW_DAYS = 28  # the headline's window (measurement.MENTION_WINDOW_DAYS)

# Who has to act for the fix to happen.
#   own        the brand's own site, profiles or facts: the brand decides
#   influence  someone else's page, with a normal route in (a profile to
#              claim, a thread to answer, an editor's correction form)
#   earn       someone else chooses whether the brand appears at all
CONTROL_WEIGHT = {"own": 1.0, "influence": 0.6, "earn": 0.3}
EVIDENCE_WEIGHT = {"official": 1.0, "strong": 0.8, "moderate": 0.6, "emerging": 0.4}

# Score (in points of the audience-weighted answer share) to band, for a play
# scored on its own. A generated list is re-banded relative to itself
# (assign_bands), which is what the product shows.
BAND_HIGH = 2.0
BAND_MEDIUM = 0.5

# The areas a recommendation can sit in, in the order the page lists them.
# Each is a different kind of work, usually with a different owner.
CATEGORIES: dict[str, dict[str, str]] = {
    "structure": {"label": "Website structure",
                  "asks": "Can AI reach and read your site?"},
    "content": {"label": "Website content",
                "asks": "Do your pages answer what buyers ask?"},
    "accuracy": {"label": "Facts and accuracy",
                 "asks": "Is what AI says about you right?"},
    "third_party": {"label": "Third-party mentions",
                    "asks": "Are you on the pages AI cites?"},
    "reviews": {"label": "Reviews and ratings",
                "asks": "What do review sites say about you?"},
    "community": {"label": "Community and video",
                  "asks": "Are you in the conversations AI quotes?"},
    "platforms": {"label": "Listings and platforms",
                  "asks": "Do stores and platforms list you correctly?"},
    # Not ranked: these change what can be measured, not what answers say.
    "setup": {"label": "Measurement", "asks": "What would let us tell you more?"},
}
RANKED_CATEGORIES = tuple(c for c in CATEGORIES if c != "setup")


def category_label(category: str) -> str:
    return CATEGORIES.get(category, {}).get("label", "")


# The words the product uses for who has to act.
CONTROL_LABELS = {
    "own": "In your control",
    "influence": "You can influence it",
    "earn": "Has to be earned",
}


def control_label(control: str) -> str:
    return CONTROL_LABELS.get(control, "")


@dataclass(frozen=True)
class Answer:
    id: int
    query_text: str
    surface: str
    family: str
    run_id: int
    named: bool


@dataclass
class Reach:
    """What a set of answers amounts to: counts for display, weighted shares
    for the score."""

    answers: int = 0
    missing: int = 0          # answers with the problem (default: brand not named)
    share: float = 0.0        # audience-weighted share of the universe, 0-1
    gap: float = 0.0          # ...that also has the problem, 0-1
    families: list[str] = field(default_factory=list)
    questions: int = 0
    runs: int = 0


class Universe:
    """Every measured answer in the window, each with its audience weight.

    scope "competitive" is the headline's population: ok search answers to
    active, unbranded, non-agent questions, generic persona only. "branded"
    is the answers about the brand itself (what accuracy is judged on); "all"
    is both. Weights sum to 1 over the universe: a family's audience weight,
    spread evenly over that family's answers."""

    def __init__(self, session: Session, tenant_id: int, *, scope: str = "competitive",
                 days: int = WINDOW_DAYS) -> None:
        self.scope = scope
        since = datetime.now(UTC) - timedelta(days=days)
        conds: list[Any] = [
            Result.tenant_id == tenant_id,
            Result.status == ResultStatus.ok,
            Result.variant == ResultVariant.search,
            col(Result.created_at) >= since,
        ]
        if scope == "competitive":
            off = _off_score_query_texts(session, tenant_id)
            if off:
                conds.append(col(Result.query_text).not_in(off))
        elif scope == "branded":
            branded = [q.text for q in session.exec(
                select(Query).where(Query.tenant_id == tenant_id,
                                    Query.branded == True)).all()]  # noqa: E712
            # No branded questions: an empty universe (a real FALSE, since
            # Postgres rejects a placeholder string with a NUL in it).
            conds.append(col(Result.query_text).in_(branded) if branded else false())
        seg, _segment = _generic_only(session, conds)
        conds.extend(seg)
        # Kept so callers can join other tables to the same answers without
        # passing thousands of ids through an IN list.
        self.conds: list[Any] = conds

        named = set(session.exec(
            select(col(Mention.result_id))
            .join(Result, col(Result.id) == col(Mention.result_id))
            .where(*conds, Mention.entity_type == "brand")
            .distinct()
        ).all())
        self.answers: dict[int, Answer] = {}
        per_family: dict[str, int] = defaultdict(int)
        for rid, query_text, surface, run_id in session.exec(
            select(col(Result.id), col(Result.query_text), col(Result.surface),
                   col(Result.run_id)).where(*conds)
        ).all():
            if rid is None:
                continue
            surface = str(surface)
            fam = family_of(surface)
            per_family[fam] += 1
            self.answers[rid] = Answer(rid, query_text, surface, fam, run_id, rid in named)

        weights = engine_weights(session.get(Tenant, tenant_id))
        pooled = {f: float(weights.get(f, 0)) for f in per_family}
        total = sum(pooled.values())
        if total <= 0:  # nothing measured carries a weight: every answer one vote
            pooled = {f: float(n) for f, n in per_family.items()}
            total = sum(pooled.values())
        self.family_share: dict[str, float] = (
            {f: w / total for f, w in pooled.items()} if total else {}
        )
        self._w: dict[str, float] = {
            f: self.family_share[f] / n for f, n in per_family.items() if n
        }
        self.runs = len({a.run_id for a in self.answers.values()})
        self.questions = len({a.query_text for a in self.answers.values()})

    def __len__(self) -> int:
        return len(self.answers)

    def where(self, pred: Callable[[Answer], bool]) -> list[int]:
        return [a.id for a in self.answers.values() if pred(a)]

    def for_query(self, query_text: str, families: Iterable[str] | None = None) -> list[int]:
        fams = set(families) if families is not None else None
        return self.where(lambda a: a.query_text == query_text
                          and (fams is None or a.family in fams))

    def for_families(self, families: Iterable[str]) -> list[int]:
        fams = set(families)
        return self.where(lambda a: a.family in fams)

    def reach(self, ids: Iterable[int] | None = None, *,
              problem: Callable[[Answer], bool] | None = None) -> Reach:
        """Reach of the answers in `ids` (all of them when None). `problem`
        says which of them count toward the gap; by default, the ones that
        don't name the brand."""
        rows = (list(self.answers.values()) if ids is None
                else [self.answers[i] for i in set(ids) if i in self.answers])
        has_problem = problem or (lambda a: not a.named)
        r = Reach()
        fams: dict[str, float] = defaultdict(float)
        for a in rows:
            w = self._w.get(a.family, 0.0)
            r.answers += 1
            r.share += w
            fams[a.family] += w
            if has_problem(a):
                r.missing += 1
                r.gap += w
        r.families = [f for f, _w in sorted(fams.items(), key=lambda kv: (-kv[1], kv[0]))]
        r.questions = len({a.query_text for a in rows})
        r.runs = len({a.run_id for a in rows})
        return r


def band(points: float) -> str:
    return "high" if points >= BAND_HIGH else "medium" if points >= BAND_MEDIUM else "low"


def priority_of(points: float) -> int:
    """The 0-100 sort key stored on the row. Logarithmic, so two very large
    scores still sort apart instead of both pinning at 100."""
    return max(1, min(100, round(22 * math.log2(1 + max(points, 0.0)))))


def _pct(x: float) -> str:
    p = 100 * x
    if p <= 0:
        return "0%"
    if p < 1:
        return "under 1%"
    return f"{round(p)}%" if p >= 10 else f"{round(p, 1):g}%"


def engines_phrase(families: list[str], universe: Universe | None = None, n: int = 3) -> str:
    """"ChatGPT, Gemini and 2 more", or "every engine" when it is all of them."""
    if universe is not None and families and set(families) >= set(universe.family_share):
        if len(families) > 1:
            return "every engine you measure"
    labels = [FAMILY_LABELS.get(f, f) for f in families]
    if len(labels) > n:
        return ", ".join(labels[:n]) + f" and {len(labels) - n} more"
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def describe(reach: Reach, universe: Universe | None = None) -> str:
    """The measured half of the impact, as one sentence."""
    if not reach.answers:
        return ""
    named = reach.answers - reach.missing
    where = engines_phrase(reach.families, universe)
    noun = "answer" if reach.answers == 1 else "answers"
    return (f"Touches {_pct(reach.share)} of your measured answers "
            f"({reach.answers:,} {noun}{', ' + where if where else ''}); "
            f"you're named in {named:,} of them.")


def impact(
    reach: Reach | None,
    *,
    control: str,
    evidence: str,
    directness: float = 1.0,
    severity: float = 1.0,
    risk: float = 0.0,
    floor: float = 0.0,
    basis: str = "",
    universe: Universe | None = None,
    at_stake: bool = False,
) -> dict:
    """Score a recommendation.

    directness  0-1: how squarely the fix acts on the answers it touches
                (unblocking a crawler makes pages eligible; it doesn't write
                the answer)
    severity    multiplier for a problem worse than being left out (a wrong
                fact told to a buyer)
    risk        0-1: the share of touched answers at stake even though they
                name the brand today (a cited page that now errors)
    floor       the least this can score when no measured answer shows it
                yet (a noindex tag on a page nothing has cited)
    at_stake    every touched answer carries the problem (a wrong fact, a
                page that errors), so "named in N of them" is left out"""
    odds = (CONTROL_WEIGHT.get(control, 0.3) * EVIDENCE_WEIGHT.get(evidence, 0.4)
            * max(0.0, min(1.0, directness)))
    exposed = max(reach.gap, risk * reach.share) if reach else 0.0
    measured = 100 * exposed * odds * severity
    points = max(measured, floor)
    out: dict[str, Any] = {
        "score": round(points, 2),
        "band": band(points),
        "measured": bool(reach and reach.answers and measured >= floor),
        "basis": basis or (describe(reach, universe) if reach else ""),
    }
    if reach and reach.answers:
        out.update({
            "answers": reach.answers,
            "share_pct": round(100 * reach.share, 1),
            "questions": reach.questions,
            "engines": [FAMILY_LABELS.get(f, f) for f in reach.families],
        })
        if not at_stake:
            out["named"] = reach.answers - reach.missing
    return out


# Banding is relative to the list, because the list is what gets triaged:
# the plays that together carry the first half of the projected impact are
# high, the next 35% medium, the rest low. The top play is always high. A
# play standing on its floor (no measured answer shows it yet) is never high.
BAND_HIGH_MASS = 0.5
BAND_MEDIUM_MASS = 0.85


def assign_bands(impacts: list[dict]) -> None:
    """Set "band" on each impact record, in place, relative to the others."""
    ranked = sorted((i for i in impacts if i.get("score")), key=lambda i: -i["score"])
    total = sum(i["score"] for i in ranked)
    seen = 0.0
    for i in ranked:
        if seen < BAND_HIGH_MASS * total:
            b = "high" if i.get("measured") else "medium"
        elif seen < BAND_MEDIUM_MASS * total:
            b = "medium"
        else:
            b = "low"
        i["band"] = b
        seen += i["score"]
