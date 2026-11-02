"""The audience toggle picks which consumer tier each API engine is asked as,
and the pins behind it cannot quietly go stale (M62)."""

from datetime import date, timedelta

from api.consumer_models import (
    AUDIENCES,
    CONSUMER_MODELS,
    DEFAULT_AUDIENCE,
    STALE_AFTER_DAYS,
    model_for,
    models_for,
    pins_status,
    tier_for,
)
from engine.llm.policy import FORBIDDEN_MODEL_SUBSTRINGS


def test_audience_maps_to_tier():
    assert tier_for("d2c") == "free"
    assert tier_for("b2b") == "paid"
    # Unknown or missing reads as the default, never as an error mid-run.
    assert tier_for(None) == tier_for(DEFAULT_AUDIENCE)
    assert tier_for("enterprise") == tier_for(DEFAULT_AUDIENCE)


def test_model_follows_audience_and_falls_back_when_unpinned():
    for surface, pin in CONSUMER_MODELS.items():
        assert model_for(surface, "d2c", "x") == pin.free
        assert model_for(surface, "b2b", "x") == pin.paid
    assert model_for("copilot_web", "b2b", "configured") == "configured"
    assert set(models_for("b2b")) == set(CONSUMER_MODELS)


def test_every_api_engine_is_pinned_with_a_real_consumer_model():
    from worker.jobs import A_ADAPTERS

    missing = set(A_ADAPTERS) - set(CONSUMER_MODELS)
    assert not missing, f"API engines with no audience pin: {sorted(missing)}"
    for pin in CONSUMER_MODELS.values():
        for model in (pin.free, pin.paid):
            assert model and not any(b in model.lower() for b in FORBIDDEN_MODEL_SUBSTRINGS)
            assert "contributor" not in model  # Meta's training-opt-in models
        date.fromisoformat(pin.as_of)
        assert pin.source


def test_pins_status_reports_age():
    today = date(2026, 11, 2)
    status = {s["surface"]: s for s in pins_status(today)}
    assert status["openai_api"]["age_days"] == 0 and not status["openai_api"]["stale"]
    later = today + timedelta(days=STALE_AFTER_DAYS + 1)
    assert all(s["stale"] for s in pins_status(later))


def test_pins_are_not_stale():
    """A reminder with teeth: the consumer apps change what they serve every
    few weeks, and a pin that outlives that measures a product nobody uses.
    When this fails, check each app's free and paid tier, update
    api/consumer_models.py (model, as_of, source), add any new price to
    engine/costs.py, and note it in DECISIONS.md."""
    stale = [s for s in pins_status() if s["stale"]]
    assert not stale, (
        "Consumer model pins older than "
        f"{STALE_AFTER_DAYS} days: "
        + ", ".join(f"{s['surface']} (as of {s['as_of']}, {s['age_days']} days)" for s in stale)
        + ". Re-check what each app serves and re-pin (see api/consumer_models.py)."
    )


def test_audiences_are_two_and_labelled():
    from api.consumer_models import AUDIENCE_LABELS

    assert set(AUDIENCES) == {"d2c", "b2b"} == set(AUDIENCE_LABELS)
