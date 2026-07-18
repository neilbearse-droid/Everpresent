"""Open out-of-list entity extraction (GoDaddy step 4 — the "who else shows up"
whitespace slide).

The deterministic mention detector (mentions.py) only finds the brand and the
configured competitors. This finds the products/companies an answer recommends
that AREN'T in the tracked set — "the AI recommends Square and Toast to a
restaurant owner, and none of them is on your list" is a category/opportunity
slide in itself. Extraction is an LLM call (routed through engine/llm), but the
prompt building, response parsing, and tracked-set filtering here are PURE and
fixture-tested — no network."""

import json
import re

EXTRACTION_VERSION = "entities-v1"

_EXTRACTION_SYSTEM = (
    "You extract the names of products, brands, or companies that an AI answer "
    "recommends or names as options. Return ONLY a compact JSON array of "
    "strings — the canonical product/company names, no descriptions, no "
    "duplicates. If none, return []."
)


def build_extraction_prompt(answer_text: str) -> str:
    return (
        "Extract every product, brand, or company named as an option or "
        "recommendation in the following AI answer. Return a JSON array of the "
        "canonical names only.\n\nAnswer:\n" + answer_text.strip()
    )


_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def parse_entities(raw: str) -> list[str]:
    """Parse the LLM's JSON array of names, tolerant of code fences or prose
    around it. Returns a de-duplicated, order-preserving list of clean strings;
    [] on anything unparseable (extraction never crashes processing)."""
    if not raw:
        return []
    match = _JSON_ARRAY.search(raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        name = item.strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def filter_untracked(names: list[str], tracked_aliases: list[str]) -> list[str]:
    """Drop names that are the tracked brand or a tracked competitor (by
    normalized exact OR containment match, so 'GoDaddy.com' and 'GoDaddy' both
    filter against tracked 'GoDaddy'). What remains is the whitespace: names the
    AI surfaces that the tenant isn't tracking."""
    tracked = [t for t in (_norm(a) for a in tracked_aliases) if t]
    out: list[str] = []
    for name in names:
        n = _norm(name)
        if not n:
            continue
        if any(n == t or t in n or n in t for t in tracked):
            continue
        out.append(name)
    return out
