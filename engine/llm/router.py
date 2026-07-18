"""Governed utility-LLM router (§4 model policy).

The ONLY place in the codebase that dispatches a utility LLM call. Every call is
gated by assert_runtime_model_allowed (the §4 allowlist + the build-time-model
ban), so a forbidden or build-time-only model can never reach the wire. Implemented
against the Anthropic Messages REST API with httpx — no vendor SDK dependency,
mirroring the retriever modules.

Utility calls are the platform's own extraction/summarization work (open entity
extraction, corrective-content drafting), distinct from the *measured* answer
engines in engine/retrievers/ — those are the product's subject, this is the
product's tooling. Sync by design: it runs from the (sync) post-run processing
pass; the caller parallelizes with a thread pool when it has many calls."""

import time

import httpx

from engine.llm.policy import assert_runtime_model_allowed

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class UtilityLLMError(RuntimeError):
    """A utility-LLM call failed after retries (network/HTTP), distinct from a
    policy violation (which is a programming error, not a runtime condition)."""


def complete(
    prompt: str,
    *,
    model: str,
    api_key: str,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    max_attempts: int = 3,
    _sleep=time.sleep,
) -> str:
    """Single-turn completion. Returns the assistant's text. Raises
    ModelPolicyViolation (before any network) for a disallowed model, or
    UtilityLLMError when the API fails after retries."""
    assert_runtime_model_allowed(model)
    if not api_key:
        raise UtilityLLMError("no Anthropic API key configured for utility LLM")
    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    last_exc: Exception | None = None
    with httpx.Client(timeout=timeout_s) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.post(ANTHROPIC_MESSAGES_URL, json=body, headers=headers)
            except httpx.HTTPError as exc:  # network error — retry
                last_exc = exc
                if attempt < max_attempts:
                    _sleep(2**attempt)
                    continue
                raise UtilityLLMError(f"utility LLM network error: {exc}") from exc
            if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                _sleep(2**attempt)
                continue
            if resp.status_code >= 400:
                raise UtilityLLMError(f"utility LLM HTTP {resp.status_code}: {resp.text[:200]}")
            return parse_message_text(resp.json())
    raise UtilityLLMError(f"utility LLM exhausted retries: {last_exc}")  # pragma: no cover


def parse_message_text(payload: dict) -> str:
    """Concatenate text blocks from a Messages API response. Pure, fixture
    tested — tolerant of null/missing content like the retriever parsers."""
    parts: list[str] = []
    for block in payload.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts).strip()
