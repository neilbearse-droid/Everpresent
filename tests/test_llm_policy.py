"""Merge-blocking guard: no Mythos-class model may be reachable from runtime
configuration. This test is not to be weakened (§11.3)."""

from pathlib import Path

import pytest

from engine.llm.policy import (
    FORBIDDEN_MODEL_SUBSTRINGS,
    RUNTIME_LLM_ALLOWLIST,
    ModelPolicyViolation,
    assert_runtime_model_allowed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runtime configuration surfaces: env samples and any YAML/JSON config in the
# Python services. Docs and this test/policy module discuss the constraint by
# name, so they are exempt; app/ is scanned for env files only.
CONFIG_GLOBS = [
    ".env*",
    "api/**/*.py",
    "api/**/*.yaml",
    "api/**/*.yml",
    "api/**/*.json",
    "worker/**/*.py",
    "engine/**/*.yaml",
    "engine/**/*.yml",
    "engine/**/*.json",
    "infra/**/*",
    "app/.env*",
]
EXEMPT = {REPO_ROOT / "engine" / "llm" / "policy.py"}


def test_allowlist_contains_no_mythos_class_model():
    for model in RUNTIME_LLM_ALLOWLIST:
        for banned in FORBIDDEN_MODEL_SUBSTRINGS:
            assert banned not in model.lower()


def test_router_rejects_fable():
    with pytest.raises(ModelPolicyViolation):
        assert_runtime_model_allowed("claude-fable-5")
    with pytest.raises(ModelPolicyViolation):
        assert_runtime_model_allowed("claude-opus-4-8")  # capable, but not allowlisted


def test_router_accepts_allowlisted_models():
    for model in RUNTIME_LLM_ALLOWLIST:
        assert assert_runtime_model_allowed(model) == model


def test_no_forbidden_model_string_in_runtime_config():
    offenders: list[str] = []
    for pattern in CONFIG_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file() or path in EXEMPT:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for banned in FORBIDDEN_MODEL_SUBSTRINGS:
                if banned in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: contains {banned!r}")
    assert not offenders, "Mythos-class model reference in runtime config:\n" + "\n".join(offenders)
