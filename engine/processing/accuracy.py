"""Factual-accuracy check (§AEO-plan M4).

"One confidently wrong AI answer about pricing or accreditation at scale is a
bigger problem than a missing citation." This scans each answer against a
per-tenant fact sheet and flags contradictions. Deterministic and
precision-first — better to miss a soft error than to cry wolf on a correct
answer — so it supports two high-confidence checks:

- disallowed: a claim that must never be made about the brand appears verbatim
  (e.g. "not accredited", "no longer offers the program").
- numeric: a sentence about a tracked subject states a same-unit number that
  contradicts the known-correct value (e.g. tuition, pass rate).

Entity/name mismatches are intentionally out of scope for v1 (too noisy to flag
deterministically). Pure text logic — fixture-tested, no LLM, no network.
"""

import re
from dataclasses import dataclass

DETECTOR_VERSION = "accuracy-v1"

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
_NUM_RE = re.compile(r"(\$\s?[\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?\s?%)|(\b[\d,]+(?:\.\d+)?\b)")


@dataclass
class FactSpec:
    id: int
    category: str
    label: str
    subject: str
    aliases: list[str]
    kind: str  # "numeric" | "disallowed"
    expected: str


@dataclass
class AccuracyHit:
    fact_id: int
    category: str
    severity: str  # "high" | "medium"
    subject: str
    expected: str
    snippet: str
    detail: str
    stated: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


_DECIMAL = re.compile(r"(\d)\.(\d)")
_DOT = chr(0xF8FF)  # private-use placeholder for a decimal point during split


def _sentences(text: str) -> list[str]:
    # Protect decimal points (e.g. $1,000.50) so they aren't treated as
    # sentence terminators, then restore them after splitting.
    protected = _DECIMAL.sub(r"\1" + _DOT + r"\2", text)
    return [
        s.replace(_DOT, ".").strip()
        for s in _SENTENCE_RE.findall(protected)
        if s.strip()
    ]


def _sentences(text: str) -> list[str]:
    # Protect decimal points (e.g. $1,000.50) so they aren't treated as
    # sentence terminators, then restore them.
    protected = _DECIMAL.sub("\\1\\2", text)
    return [s.replace("", ".").strip() for s in _SENTENCE_RE.findall(protected) if s.strip()]


def _numbers(s: str) -> list[tuple[str, float, str]]:
    """(kind, value, raw) for each number, where kind ∈ currency|percent|plain."""
    out: list[tuple[str, float, str]] = []
    for cur, pct, plain in _NUM_RE.findall(s):
        try:
            if cur:
                out.append(("currency", float(cur.replace("$", "").replace(",", "").strip()), cur))
            elif pct:
                out.append(("percent", float(pct.replace("%", "").replace(",", "").strip()), pct))
            elif plain:
                out.append(("plain", float(plain.replace(",", "")), plain))
        except ValueError:  # pragma: no cover - regex already constrains shape
            continue
    return out


def _mentions_subject(sentence_low: str, subj_low: str, alias_lows: list[str]) -> bool:
    return bool(subj_low) and subj_low in sentence_low or any(a in sentence_low for a in alias_lows)


def check_text(text: str, facts: list[FactSpec]) -> list[AccuracyHit]:
    """Contradictions between `text` and the fact sheet. Empty facts → empty."""
    if not text or not facts:
        return []
    low_text = _norm(text)
    sents = _sentences(text)
    low_sents = [_norm(s) for s in sents]
    hits: list[AccuracyHit] = []

    for f in facts:
        subj_low = _norm(f.subject)
        alias_lows = [n for n in (_norm(a) for a in f.aliases) if n]

        if f.kind == "disallowed":
            needle = _norm(f.expected)
            if needle and needle in low_text:
                snippet = next(
                    (s for s, ls in zip(sents, low_sents, strict=False) if needle in ls),
                    f.expected,
                )
                hits.append(AccuracyHit(
                    fact_id=f.id, category=f.category, severity="high",
                    subject=f.subject, expected=f.expected, snippet=snippet[:200],
                    detail=f"States a disallowed claim about {f.subject}: “{f.expected}”.",
                    stated=f.expected,
                ))
            continue

        if f.kind == "numeric":
            exp_nums = _numbers(f.expected)
            if not exp_nums:
                continue
            exp_kind, exp_val, _ = exp_nums[0]
            for s, ls in zip(sents, low_sents, strict=False):
                if not _mentions_subject(ls, subj_low, alias_lows):
                    continue
                same_kind = [(v, raw) for (k, v, raw) in _numbers(s) if k == exp_kind]
                if not same_kind:
                    continue
                # Correct value present in the sentence → no contradiction.
                if any(abs(v - exp_val) <= 0.001 for v, _ in same_kind):
                    continue
                wrong_v, wrong_raw = same_kind[0]
                hits.append(AccuracyHit(
                    fact_id=f.id, category=f.category, severity="high",
                    subject=f.subject, expected=f.expected, snippet=s[:200],
                    detail=(f"States {f.subject} as {wrong_raw}, but the correct value is "
                            f"{f.expected}."),
                    stated=wrong_raw,
                ))
                break
    return hits
