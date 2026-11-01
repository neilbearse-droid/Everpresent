"""Week-one measurement fixes from the October 2026 sweep: the headline reads
generic answers only (gap 1), engine changes are carried into alerts and the
proof of fixes (gap 2), and the alert bar applies a Holm correction (gap 24)."""

from datetime import UTC, date, datetime, timedelta

import pytest

import api.dashboards.overview as overview_mod
from api.dashboards.measurement import (
    _holm_survivors,
    alerts,
    kpi_scorecard,
    mention_rates,
    topic_scorecard,
)
from api.dashboards.overview import engine_breaks
from api.models import (
    BrandProfile,
    Intervention,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)


def _tenant(db, queries=("best crm",), gl="ca"):
    t = Tenant(name="Acme", slug="acme", aio_geo={"gl": gl, "hl": "en"})
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    for q in queries:
        db.add(Query(tenant_id=t.id, text=q))
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return t, run


def _answers(db, t, run, *, n, named, days_ago=3, surface=SurfaceCode.openai_api,
             segment="generic", query="best crm", model="", when=None):
    """n answers in one batch, the first `named` naming the brand."""
    created = when or (utcnow() - timedelta(days=days_ago))
    rows = [Result(run_id=run.id, tenant_id=t.id, query_text=query,
                   persona_name=segment or "(serp)", persona_segment=segment, surface=surface,
                   variant=ResultVariant.search, status=ResultStatus.ok, created_at=created,
                   served_model=model)
            for _ in range(n)]
    db.add_all(rows)
    db.flush()
    db.add_all([Mention(result_id=r.id, tenant_id=t.id, entity_type="brand", entity_name="Acme",
                        position=0, rank=1) for r in rows[:named]])
    db.commit()


@pytest.fixture()
def no_announced_breaks(monkeypatch):
    """Keep the alert tests independent of the calendar: the announced October
    breaks fall inside the trailing window on some days and not others."""
    monkeypatch.setattr(overview_mod, "SERIES_BREAKS", [])
    monkeypatch.setattr(overview_mod, "_GEO_SERIES_BREAKS", [])


# --- gap 1: persona answers do not pool into the headline ---------------------


def test_persona_answers_do_not_move_the_headline(db_session):
    t, run = _tenant(db_session)
    _answers(db_session, t, run, n=40, named=10)                       # generic: 25%
    _answers(db_session, t, run, n=10, named=10, segment="",           # a SERP, no persona
             surface=SurfaceCode.google_aio)
    _answers(db_session, t, run, n=40, named=40, segment="founder")    # persona cell

    m = mention_rates(db_session, t.id)
    assert m["segment"] == "generic"
    # Generic + SERP answers only: 20 of 50, not 60 of 90. The pooled rate
    # weights ChatGPT 40 and Google AI Overviews 20 (api.engine_weights).
    assert m["overall"]["answers"] == 50 and m["overall"]["mentioned"] == 20
    assert m["overall"]["rate"] == 50.0           # (40·0.25 + 20·1.0) / 60
    assert m["overall"]["equal"]["rate"] == 40.0  # one answer, one vote
    assert {e["surface"]: e["answers"] for e in m["engines"]} == {"openai_api": 40,
                                                                  "google_aio": 10}

    card = kpi_scorecard(db_session, t.id)
    assert card["segment"] == "generic"
    assert card["mention_rates"]["overall"]["answers"] == 50
    # Latest answer per (question, engine): two generic cells, no persona cell.
    assert card["prominence"]["measured"] == 2
    (row,) = topic_scorecard(db_session, t.id)
    assert row["answers"] == 50 and row["rate"] == 40.0


def test_legacy_tenant_without_a_generic_cell_pools_every_segment(db_session):
    t, run = _tenant(db_session)
    _answers(db_session, t, run, n=20, named=10, segment="seg0")
    _answers(db_session, t, run, n=20, named=0, segment="seg1")

    m = mention_rates(db_session, t.id)
    assert m["segment"] == "all"
    assert m["overall"]["answers"] == 40 and m["overall"]["rate"] == 25.0
    card = kpi_scorecard(db_session, t.id)
    assert card["segment"] == "all" and card["prominence"]["measured"] == 1
    (row,) = topic_scorecard(db_session, t.id)
    assert row["answers"] == 40


# --- gap 2: engine changes in alerts and proof --------------------------------


def test_october_2026_breaks_apply_per_surface_and_country(db_session):
    t, run = _tenant(db_session)
    for s in (SurfaceCode.chatgpt_web, SurfaceCode.google_aio, SurfaceCode.google_ai_mode):
        _answers(db_session, t, run, n=1, named=0, surface=s, segment="")
    got = {(b["date"], b["surface"])
           for b in engine_breaks(db_session, t.id, "2026-10-01", "2026-10-31")}
    assert got == {("2026-10-08", "chatgpt_web"), ("2026-10-15", "google_aio"),
                   ("2026-10-15", "google_ai_mode"), ("2026-10-28", "google_ai_mode"),
                   ("2026-10-29", "chatgpt_web")}
    # Ads in AI Mode began in Canada; a US tenant gets no Oct 28 break.
    t.aio_geo = {"gl": "us", "hl": "en"}
    db_session.add(t)
    db_session.commit()
    dates = [b["date"] for b in engine_breaks(db_session, t.id, "2026-10-01", "2026-10-31")]
    assert "2026-10-28" not in dates
    # A break on the window's first day splits nothing; an unmeasured engine
    # (no ChatGPT (web) answers after the second tenant) is not noted.
    t2 = Tenant(name="Beta", slug="beta")
    db_session.add(t2)
    db_session.commit()
    assert engine_breaks(db_session, t2.id, "2026-10-01", "2026-10-31") == []


def test_alert_notes_an_engine_change_and_withholds_the_pooled_verdict(
    db_session, monkeypatch, no_announced_breaks
):
    t, run = _tenant(db_session)
    when = (utcnow() - timedelta(days=10)).date().isoformat()
    monkeypatch.setattr(overview_mod, "SERIES_BREAKS",
                        [(when, SurfaceCode.chatgpt_web, "ChatGPT changed its model.")])
    _answers(db_session, t, run, n=60, named=42, days_ago=20, surface=SurfaceCode.chatgpt_web,
             segment="")
    _answers(db_session, t, run, n=60, named=18, days_ago=3, surface=SurfaceCode.chatgpt_web,
             segment="")
    got = {a["kind"]: a for a in alerts(db_session, t.id)}
    drop = got["visibility_drop"]
    assert drop["text"].startswith("ChatGPT (web): mention rate fell 40.0pt")
    assert f"coincides with an engine change on {when}" in drop["text"]
    # The pooled rate also fell, but its verdict is withheld and says why.
    held = got["series_break"]
    assert held["severity"] == "medium" and held["text"].startswith("Overall")
    assert "withheld" in held["text"] and when in held["text"]
    assert not any(a["text"].startswith("Overall") for a in got.values()
                   if a["kind"] != "series_break")


def test_observed_model_switch_counts_as_an_engine_change(db_session, no_announced_breaks):
    t, run = _tenant(db_session)
    _answers(db_session, t, run, n=60, named=42, days_ago=20, model="gpt-5.6-terra")
    _answers(db_session, t, run, n=60, named=18, days_ago=3, model="gpt-6-luna")
    got = {a["kind"]: a for a in alerts(db_session, t.id)}
    assert "coincides with an engine change on" in got["visibility_drop"]["text"]
    assert "gpt-6-luna" in got["visibility_drop"]["text"]
    assert "series_break" in got


TODAY = date(2026, 10, 4)
SHIP = datetime(2026, 9, 6, tzinfo=UTC)
FIXED, OTHER = "best registrar for small business", "cheapest hosting"


def _proof_setup(db, *, clean_engine=False):
    """Mirrors tests/test_proof.py: 20% → 60% on the fixed question against
    a flat control, but ChatGPT switched models between the two windows."""
    t, run = _tenant(db, queries=(FIXED, OTHER))
    before = datetime(2026, 8, 27, 12, tzinfo=UTC)
    after = datetime(2026, 9, 16, 12, tzinfo=UTC)
    _answers(db, t, run, n=30, named=6, query=FIXED, when=before, model="gpt-5.6-terra")
    _answers(db, t, run, n=30, named=18, query=FIXED, when=after, model="gpt-6-luna")
    _answers(db, t, run, n=30, named=9, query=OTHER, when=before, model="gpt-5.6-terra")
    _answers(db, t, run, n=30, named=9, query=OTHER, when=after, model="gpt-6-luna")
    if clean_engine:
        for q, named in ((FIXED, 6), (OTHER, 9)):
            _answers(db, t, run, n=30, named=named, query=q, when=before,
                     surface=SurfaceCode.claude_api)
        for q, named in ((FIXED, 18), (OTHER, 9)):
            _answers(db, t, run, n=30, named=named, query=q, when=after,
                     surface=SurfaceCode.claude_api)
    db.add(Intervention(tenant_id=t.id, query_text=FIXED, description="New comparison page",
                        shipped_at=SHIP))
    db.commit()
    return t


def test_proof_is_confounded_when_the_only_engine_changed(db_session):
    from api.proof_service import intervention_proof

    t = _proof_setup(db_session)
    d = intervention_proof(db_session, t.id, today=TODAY)
    it = d["items"][0]
    assert it["status"] == "confounded"
    assert it["headline"].startswith("An engine change on 2026-09-16 (ChatGPT) overlaps")
    assert "the lift can't be attributed to the fix" in it["headline"]
    assert [b["surface"] for b in it["breaks"]] == ["openai_api"]
    m = next(s for s in it["signals"] if s["key"] == "mentions")
    # Only the answers from the engine state the fix shipped in are kept:
    # every after-window answer came from the new model, so none is left.
    assert m["before_n"] == 30 and m["after_n"] == 0
    assert "ChatGPT answers limited to the engine state the fix shipped in" in m["note"]
    assert "engine change on 2026-09-16" in m["note"]
    assert "1 can't be read because an engine changed in the window" in d["summary"]


def test_proof_survives_on_the_engine_that_did_not_change(db_session):
    from api.proof_service import intervention_proof

    t = _proof_setup(db_session, clean_engine=True)
    it = intervention_proof(db_session, t.id, today=TODAY)["items"][0]
    assert it["status"] == "proven"
    m = next(s for s in it["signals"] if s["key"] == "mentions")
    # Claude on both sides plus ChatGPT's pre-switch answers on the before side.
    assert m["before_n"] == 60 and m["after_n"] == 30 and m["verdict"] == "up"
    assert "ChatGPT answers limited to the engine state the fix shipped in" in it["headline"]


# --- gap 24: Holm correction on the alert bar ---------------------------------


def test_holm_survivors():
    assert _holm_survivors([0.04] * 8 + [0.9]) == set()
    assert _holm_survivors([0.001, 0.04, 0.04]) == {0}
    assert _holm_survivors([None, 0.01]) == {1}        # untested rows don't count
    assert _holm_survivors([0.001, 0.002, 0.5]) == {0, 1}


_EIGHT = (SurfaceCode.openai_api, SurfaceCode.claude_api, SurfaceCode.gemini_api,
          SurfaceCode.perplexity_api, SurfaceCode.meta_api, SurfaceCode.chatgpt_web,
          SurfaceCode.copilot_web, SurfaceCode.perplexity_web)


def _eight_engines(db, strong=None):
    """Eight engines at 50% in the first half; four rise to 64% and four fall
    to 36% (each p ≈ 0.046), so Overall stays flat. `strong` falls to 27%
    instead (p ≈ 0.001)."""
    t, run = _tenant(db)
    for i, s in enumerate(_EIGHT):
        _answers(db, t, run, n=100, named=50, days_ago=20, surface=s)
        after = 64 if i % 2 == 0 else (27 if s == strong else 36)
        _answers(db, t, run, n=100, named=after, days_ago=3, surface=s)
    return t


def test_eight_engines_at_p_near_five_percent_raise_no_alert(db_session, no_announced_breaks):
    t = _eight_engines(db_session)
    rates = mention_rates(db_session, t.id)
    # The table still labels each row on its own test...
    assert all(e["change"]["verdict"] in ("up", "down") for e in rates["engines"])
    assert rates["overall"]["change"]["verdict"] == "no real change"
    # ...but the alert bar, corrected across the family, stays quiet.
    assert [a for a in alerts(db_session, t.id) if a["kind"].startswith("visibility")] == []


def test_one_engine_with_a_strong_drop_still_alerts(db_session, no_announced_breaks):
    t = _eight_engines(db_session, strong=SurfaceCode.claude_api)
    got = [a for a in alerts(db_session, t.id) if a["kind"].startswith("visibility")]
    assert len(got) == 1
    assert got[0]["kind"] == "visibility_drop" and got[0]["text"].startswith("Claude: ")
