"""§12.1 calibration harness: scores the AIO classifier against Neil's 40
labeled seed queries the moment seeds/aio_labels.yaml exists. Skipped (with a
loud reason) until then — see DECISIONS.md M6."""

from pathlib import Path

import pytest
import yaml

from engine.processing.aio import classify_aio_capture
from engine.retrievers.google_aio import AIOCaptureSummary

LABELS_FILE = Path(__file__).parent.parent / "seeds" / "aio_labels.yaml"
TARGET_AGREEMENT = 0.8


@pytest.mark.skipif(
    not LABELS_FILE.exists(),
    reason="seeds/aio_labels.yaml not provided yet (§12.1 — Neil's 40 labeled "
    "queries). Copy seeds/aio_labels.example.yaml and fill in real labels.",
)
def test_classifier_agrees_with_human_labels():
    labels = yaml.safe_load(LABELS_FILE.read_text(encoding="utf-8"))["labels"]
    assert len(labels) >= 20, "calibration needs a meaningful label set"
    hits = 0
    misses = []
    for entry in labels:
        summary = AIOCaptureSummary(
            aio_present=entry["aio_present"],
            aio_position_index=entry["aio_position_index"],
            aio_text_len=entry["aio_text_len"],
            expanded=entry.get("expanded", False),
            organic_count=entry.get("organic_count", 0),
        )
        got = classify_aio_capture(summary, []).source_type
        if got == entry["expected"]:
            hits += 1
        else:
            misses.append((entry["query"], entry["expected"], str(got)))
    agreement = hits / len(labels)
    assert agreement >= TARGET_AGREEMENT, (
        f"classifier agrees on {agreement:.0%} (< {TARGET_AGREEMENT:.0%}); "
        f"misses: {misses[:10]}"
    )
