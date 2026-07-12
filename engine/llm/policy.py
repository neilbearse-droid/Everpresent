"""Runtime model policy.

Owner constraint, enforced in code: no queries through Fable.
claude-fable-5 is a build-time tool only. It must never be reachable
from runtime configuration. tests/test_llm_policy.py fails the suite if
a Mythos-class model string appears in any runtime model setting or
client config.

No file outside engine/llm/ may import a model SDK; all utility LLM
calls go through the router in this package (arrives with M3).
"""

RUNTIME_LLM_ALLOWLIST: frozenset[str] = frozenset(
    {
        "claude-haiku-4-5-20251001",  # bulk extraction, mention detection
        "claude-sonnet-4-6",  # summarization, recommendation text
    }
)

# Substrings that must never appear in a runtime model identifier or in
# runtime configuration values. Checked here and by the policy test.
FORBIDDEN_MODEL_SUBSTRINGS: tuple[str, ...] = ("fable", "mythos")


class ModelPolicyViolation(RuntimeError):
    """Raised when a runtime component asks for a model outside the allowlist."""


def assert_runtime_model_allowed(model: str) -> str:
    """Gate every utility-LLM dispatch. Returns the model id when allowed."""
    lowered = model.lower()
    for banned in FORBIDDEN_MODEL_SUBSTRINGS:
        if banned in lowered:
            raise ModelPolicyViolation(
                f"{model!r} is a build-time-only model and must never run in production"
            )
    if model not in RUNTIME_LLM_ALLOWLIST:
        raise ModelPolicyViolation(f"{model!r} is not in RUNTIME_LLM_ALLOWLIST")
    return model
