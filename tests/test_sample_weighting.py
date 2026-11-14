"""Repeated sampling follows the audience: the plan's samples_per_cell is what
the heaviest engine family gets; lighter families take fewer, cheap engines
keep the full count, and nothing drops below one."""

from api.engine_weights import DEFAULT_ENGINE_WEIGHTS, samples_for_surface


def test_samples_follow_audience_weight():
    w = DEFAULT_ENGINE_WEIGHTS
    assert samples_for_surface("openai_api", 3, w) == 3      # ChatGPT, 40
    assert samples_for_surface("gemini_api", 3, w) == 1      # Gemini, 12, costly
    assert samples_for_surface("claude_api", 3, w) == 1      # Claude, 8
    assert samples_for_surface("meta_api", 3, w) == 1        # Meta, 3
    assert samples_for_surface("perplexity_api", 3, w) == 3  # cheap: full count


def test_two_sample_plan_and_floor():
    w = DEFAULT_ENGINE_WEIGHTS
    assert samples_for_surface("openai_api", 2, w) == 2
    assert samples_for_surface("gemini_api", 2, w) == 1
    assert samples_for_surface("claude_api", 1, w) == 1
    assert samples_for_surface("openai_api", 0, w) == 1


def test_tenant_override_moves_samples():
    # A tenant whose audience is on Claude gets Claude's full samples.
    w = {**DEFAULT_ENGINE_WEIGHTS, "claude": 30, "chatgpt": 5}
    assert samples_for_surface("claude_api", 3, w) == 3
    assert samples_for_surface("openai_api", 3, w) == 1
