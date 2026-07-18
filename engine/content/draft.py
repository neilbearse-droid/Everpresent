"""Corrective/optimized content drafting (§step 5 — the closed loop).

Turns a detected gap into publishable content: for an accuracy gap, a piece that
states the correct answer clearly and is structured for AI extraction (direct
answer up top, headings, plain facts) so future answers cite it instead of the
source that carried the error. The LLM call goes through engine/llm; the prompt
building and response parsing here are PURE and fixture-tested."""

import json
import re
from dataclasses import dataclass, field

DRAFT_VERSION = "content-draft-v1"

DRAFT_SYSTEM = (
    "You are a GEO/AEO content strategist. You write concise, factual web "
    "content designed to be cited by AI answer engines: a direct answer in the "
    "first sentence, clear H2 headings, short paragraphs, no marketing fluff, no "
    "invented facts. Respond ONLY with a JSON object: "
    '{"title": "...", "body": "..."} where body is Markdown.'
)


@dataclass
class AccuracyGapContext:
    """Everything the drafter needs about a factual-accuracy gap."""

    brand_name: str
    subject: str
    wrong_claim: str  # what the engines state (the disallowed/incorrect claim)
    correct_value: str  # the ground truth from the fact sheet
    engines: list[str] = field(default_factory=list)  # engines repeating it
    snippets: list[str] = field(default_factory=list)  # example wrong sentences
    source_domains: list[str] = field(default_factory=list)  # domains feeding it


def build_accuracy_draft_prompt(ctx: AccuracyGapContext) -> str:
    lines = [
        f"Brand: {ctx.brand_name}",
        f"Topic: {ctx.subject}",
        f"What AI answers currently claim (INCORRECT): {ctx.wrong_claim}",
        f"The correct, authoritative answer: {ctx.correct_value}",
    ]
    if ctx.engines:
        lines.append(f"Engines repeating the error: {', '.join(ctx.engines)}")
    if ctx.source_domains:
        lines.append(f"Sources the wrong answers cite: {', '.join(ctx.source_domains)}")
    if ctx.snippets:
        lines.append("Example incorrect sentences:")
        lines.extend(f"- {s}" for s in ctx.snippets[:3])
    lines.append(
        "\nWrite a short, publishable page for the brand's own site that states "
        "the correct answer directly and unambiguously, so AI answer engines cite "
        "it instead of the incorrect sources. Lead with the corrected fact."
    )
    return "\n".join(lines)


_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def parse_draft(raw: str) -> tuple[str, str]:
    """(title, body) from the LLM's JSON object, tolerant of code fences/prose.
    Falls back to ('', raw) when there's no parseable JSON, so a well-formed but
    non-JSON answer still yields usable body text rather than nothing."""
    if not raw:
        return "", ""
    match = _JSON_OBJ.search(raw)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                title = str(data.get("title", "")).strip()
                body = str(data.get("body", "")).strip()
                if title or body:
                    return title, body
        except (ValueError, json.JSONDecodeError):
            pass
    return "", raw.strip()
