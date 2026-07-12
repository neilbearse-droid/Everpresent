"""End-to-end processing over a configured tenant: mentions, categorized
citations, dual-query classification, and the visibility_daily rollup."""

import pytest
from sqlmodel import select

from api.models import (
    BrandProfile,
    Competitor,
    Mention,
    QueryClassification,
    Run,
    VisibilityDaily,
)
from api.processing_service import process_run
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)


@pytest.fixture()
def configured_tenant(db_session):
    tenant = make_tenant(db_session, "smith", queries=2, personas=2)
    assert tenant.id is not None
    db_session.add(
        BrandProfile(
            tenant_id=tenant.id,
            brand_name="Smith School of Business",
            aliases=["Smith", "Queen's Smith"],
            domains=["smith.queensu.ca"],
        )
    )
    db_session.add(
        Competitor(
            tenant_id=tenant.id,
            name="Rotman School of Management",
            aliases=["Rotman"],
            domains=["rotman.utoronto.ca"],
        )
    )
    db_session.add(
        Competitor(
            tenant_id=tenant.id,
            name="Ivey Business School",
            aliases=["Ivey"],
            domains=["ivey.uwo.ca"],
        )
    )
    db_session.commit()
    return tenant


def test_full_processing_pipeline(db_session, job_env, fake_retrieve, configured_tenant):  # noqa: F811
    from worker.jobs import run_mode_a

    run_id = _pending_run(db_session, configured_tenant)
    run_mode_a(run_id)

    # Mentions: fixture text names Rotman, Smith, and Ivey in that order.
    mentions = db_session.exec(select(Mention)).all()
    per_result = {}
    for m in mentions:
        per_result.setdefault(m.result_id, []).append(m)
    assert len(per_result) == 4  # each search result
    for result_mentions in per_result.values():
        ordered = sorted(result_mentions, key=lambda m: m.rank)
        assert [m.entity_name for m in ordered] == [
            "Rotman School of Management",
            "Ivey Business School",
            "Smith School of Business",
        ]
        brand = ordered[2]
        assert brand.entity_type == "brand"
        assert brand.sentiment == "positive"  # "strongest" in the window
        assert "Smith" in brand.context_snippet

    # Citations categorized: smith.queensu.ca is a brand domain now.
    from api.models import Citation

    categories = {
        (c.domain, c.source_category) for c in db_session.exec(select(Citation)).all()
    }
    assert categories == {("ft.com", "other"), ("smith.queensu.ca", "brand")}

    # Classification: searched, cited, and the nosearch answer diverges.
    classifications = db_session.exec(select(QueryClassification)).all()
    assert len(classifications) == 2
    for c in classifications:
        assert c.web_search_likelihood == "very_likely"
        assert c.signals["web_search_calls"] == 1
        assert c.signals["citation_count"] == 2
        assert c.signals["divergence"] >= 0.45
        assert c.classifier_version == "v3.0.0"

    # Visibility rollup: one row per (surface, segment) with competitor scores.
    rows = db_session.exec(select(VisibilityDaily)).all()
    assert {(r.surface, r.persona_segment) for r in rows} == {
        ("openai_api", "seg0"),
        ("openai_api", "seg1"),
    }
    for row in rows:
        # Brand mentioned rank 3 in every result, brand-domain citation in
        # every result: 100*(0.6*1 + 0.25/3 + 0.15*1) = 83.33
        assert row.brand_score == pytest.approx(83.33, abs=0.01)
        # Rotman: rank 1, never cited: 100*(0.6 + 0.25) = 85
        assert row.competitor_scores["Rotman School of Management"] == pytest.approx(85.0)
        # Ivey: rank 2, never cited: 100*(0.6 + 0.25*0.5) = 72.5
        assert row.competitor_scores["Ivey Business School"] == pytest.approx(72.5)
        assert row.extras["result_count"] == 2
        assert row.extras["mention_rate"] == 1.0

    # Reprocessing is idempotent: same row counts, no duplicates.
    run = db_session.exec(select(Run)).one()
    process_run(db_session, run)
    assert len(db_session.exec(select(Mention)).all()) == len(mentions)
    assert len(db_session.exec(select(QueryClassification)).all()) == 2
    assert len(db_session.exec(select(VisibilityDaily)).all()) == len(rows)
