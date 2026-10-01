"""Confidence ranges and real-change flags: the statistics behind the headline
mention rate."""

from datetime import timedelta

import pytest

from engine.processing.stats import (
    change_verdict,
    rate_summary,
    two_proportion_p_value,
    wilson_interval,
)


def test_wilson_matches_reference_values():
    lo, hi = wilson_interval(42, 100)
    assert lo == pytest.approx(0.3280, abs=1e-3) and hi == pytest.approx(0.5179, abs=1e-3)
    assert wilson_interval(0, 10)[0] == 0.0 and wilson_interval(10, 10)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_small_samples_get_wide_ranges():
    narrow = rate_summary(84, 200)
    wide = rate_summary(1, 3)
    assert narrow["high"] - narrow["low"] < 15
    assert wide["high"] - wide["low"] > 60


def test_change_needs_enough_answers_and_significance():
    assert change_verdict(5, 10, 9, 10)["verdict"] == "not enough data"
    assert change_verdict(60, 200, 66, 200)["verdict"] == "no real change"   # 30% -> 33%
    up = change_verdict(60, 200, 100, 200)                                   # 30% -> 50%
    assert up["verdict"] == "up" and up["delta"] == 20.0 and up["p_value"] < 0.05
    assert change_verdict(100, 200, 60, 200)["verdict"] == "down"
    assert two_proportion_p_value(50, 100, 50, 100) == pytest.approx(1.0)


def test_mention_rates_pool_runs_and_split_the_window(db_session):
    from api.dashboards_service import mention_rates
    from api.models import (
        BrandProfile,
        Mention,
        Query,
        Result,
        ResultStatus,
        ResultVariant,
        Run,
        RunMode,
        SurfaceCode,
        Tenant,
        utcnow,
    )

    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=[]))
    db_session.add(Query(tenant_id=t.id, text="Acme reviews", branded=True))
    run = Run(tenant_id=t.id)
    db_session.add(run)
    db_session.commit()
    now = utcnow()

    def answer(days_ago, named, surface=SurfaceCode.openai_api, text="best crm"):
        r = Result(run_id=run.id, tenant_id=t.id, query_text=text, persona_name="p",
                   persona_segment="all", surface=surface, mode=RunMode.A,
                   variant=ResultVariant.search, status=ResultStatus.ok,
                   created_at=now - timedelta(days=days_ago))
        db_session.add(r)
        db_session.commit()
        if named:
            db_session.add(Mention(result_id=r.id, tenant_id=t.id, entity_type="brand",
                                   entity_name="Acme", position=0, rank=1))
            db_session.commit()

    # First half of the 28-day window: 10/40 named. Second half: 30/40 named.
    for i in range(40):
        answer(20, named=i < 10)
        answer(3, named=i < 30)
    answer(3, named=True, surface=SurfaceCode.claude_api)
    answer(3, named=True, text="Acme reviews")  # branded: excluded
    answer(60, named=True)                      # outside the window: excluded

    out = mention_rates(db_session, t.id)
    openai = next(e for e in out["engines"] if e["surface"] == "openai_api")
    assert openai["answers"] == 80 and openai["mentioned"] == 40 and openai["rate"] == 50.0
    assert openai["low"] < 50.0 < openai["high"]
    assert openai["change"]["verdict"] == "up" and openai["change"]["delta"] == 50.0
    assert openai["prompts"] == 1
    assert out["overall"]["answers"] == 81 and out["overall"]["prompts"] == 1
