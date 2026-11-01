"""The pooled headline weights engines by audience (api.engine_weights)."""

from datetime import timedelta

from api.dashboards.measurement import alerts, mention_rates
from api.dashboards.overview import engine_breaks, overview
from api.engine_weights import DEFAULT_ENGINE_WEIGHTS, engine_weights, weight_lines
from api.models import SurfaceCode, Tenant, User, VisibilityDaily, utcnow
from engine.processing.stats import weighted_change_verdict, weighted_rate_summary
from tests.test_week_one_measurement import _answers, _tenant


def test_weighted_rate_pools_by_weight_and_drops_empty_cells():
    # ChatGPT 50% at weight 40, Perplexity 0% at weight 3: the pool sits near ChatGPT.
    s = weighted_rate_summary([(40, 50, 100), (3, 0, 100), (20, 0, 0)])
    assert s["rate"] == 46.5 and s["answers"] == 200 and s["mentioned"] == 50
    assert s["low"] < s["rate"] < s["high"]
    # One engine: the weighted rate is that engine's rate.
    assert weighted_rate_summary([(40, 30, 60)])["rate"] == 50.0
    # Weight 0 everywhere falls back to equal weights rather than nothing.
    assert weighted_rate_summary([(0, 50, 100), (0, 0, 100)])["rate"] == 25.0
    # Weight 0 beside a weighted cell is measured, not pooled.
    assert weighted_rate_summary([(40, 50, 100), (0, 100, 100)])["rate"] == 50.0
    assert weighted_rate_summary([])["answers"] == 0


def test_weighted_change_verdict():
    before = [(40, 10, 100), (12, 10, 100)]
    after = [(40, 40, 100), (12, 10, 100)]
    v = weighted_change_verdict(before, after)
    assert v["verdict"] == "up" and v["delta"] > 20 and v["p_value"] < 0.01
    assert weighted_change_verdict([(40, 1, 10)], after)["verdict"] == "not enough data"
    flat = weighted_change_verdict(before, before)
    assert flat["verdict"] == "no real change" and flat["delta"] == 0.0


def test_tenant_override_and_display_lines():
    t = Tenant(name="A", slug="a", engine_weights={"claude": 30, "bogus": 9, "meta": "x"})
    w = engine_weights(t)
    assert w["claude"] == 30 and w["meta"] == DEFAULT_ENGINE_WEIGHTS["meta"]
    assert "bogus" not in w
    lines = weight_lines(w, {"chatgpt", "claude", "perplexity"})
    assert [line["label"] for line in lines] == ["ChatGPT", "Claude", "Perplexity"]
    assert lines[0]["share_pct"] == round(100 * 40 / 73, 1)
    assert all(line["pooled"] for line in lines)
    zero = weight_lines({**w, "perplexity": 0}, {"chatgpt", "perplexity"})
    assert zero[-1] == {"family": "perplexity", "label": "Perplexity", "weight": 0,
                        "share_pct": 0.0, "pooled": False}


def test_headline_follows_the_popular_engine(db_session):
    t, run = _tenant(db_session)
    _answers(db_session, t, run, n=100, named=60, surface=SurfaceCode.openai_api)
    _answers(db_session, t, run, n=100, named=0, surface=SurfaceCode.perplexity_api)
    o = mention_rates(db_session, t.id)["overall"]
    assert o["weighting"] == "audience"
    assert o["rate"] == round(100 * (40 * 0.6 + 3 * 0.0) / 43, 1)  # 55.8
    assert o["equal"]["rate"] == 30.0  # one answer, one vote
    assert [w["label"] for w in o["weights"]] == ["ChatGPT", "Perplexity"]
    # Surfaces of one engine pool into one family: measuring ChatGPT twice
    # doesn't double its vote.
    _answers(db_session, t, run, n=100, named=0, surface=SurfaceCode.chatgpt_web, segment="")
    o2 = mention_rates(db_session, t.id)["overall"]
    assert [w["label"] for w in o2["weights"]] == ["ChatGPT", "Perplexity"]
    assert o2["rate"] == round(100 * (40 * 0.3) / 43, 1)


def test_zero_weight_engine_is_measured_not_pooled(db_session):
    t, run = _tenant(db_session)
    t.engine_weights = {"perplexity": 0}
    db_session.add(t)
    db_session.commit()
    _answers(db_session, t, run, n=100, named=60, surface=SurfaceCode.openai_api)
    _answers(db_session, t, run, n=100, named=0, surface=SurfaceCode.perplexity_api)
    m = mention_rates(db_session, t.id)
    assert m["overall"]["rate"] == 60.0 and m["overall"]["answers"] == 100
    assert {e["label"] for e in m["engines"]} == {"ChatGPT", "Perplexity"}
    perplexity = next(w for w in m["overall"]["weights"] if w["family"] == "perplexity")
    assert perplexity["pooled"] is False


def test_trend_tile_is_weighted_too(db_session):
    t, _run = _tenant(db_session)
    day = (utcnow() - timedelta(days=2)).date().isoformat()
    db_session.add_all([
        VisibilityDaily(tenant_id=t.id, date=day, surface=SurfaceCode.openai_api,
                        brand_score=80.0, competitor_scores={"Rival": 20.0}),
        VisibilityDaily(tenant_id=t.id, date=day, surface=SurfaceCode.perplexity_api,
                        brand_score=0.0, competitor_scores={"Rival": 100.0}),
    ])
    db_session.commit()
    (point,) = overview(db_session, t.id)["trend"]
    assert point["brand_score"] == round(80 * 40 / 43, 2)
    assert point["competitors"]["Rival"] == round((20 * 40 + 100 * 3) / 43, 2)


def test_weight_change_is_a_note_on_the_pooled_line_only(db_session, monkeypatch):
    import api.dashboards.overview as overview_mod

    monkeypatch.setattr(overview_mod, "SERIES_BREAKS", [])
    monkeypatch.setattr(overview_mod, "_GEO_SERIES_BREAKS", [])
    t, run = _tenant(db_session)
    when = (utcnow() - timedelta(days=5)).date().isoformat()
    t.engine_weights = {"claude": 30}
    t.engine_weights_changed_on = when
    db_session.add(t)
    db_session.commit()
    lo = (utcnow() - timedelta(days=28)).date().isoformat()
    hi = utcnow().date().isoformat()
    (note,) = engine_breaks(db_session, t.id, lo, hi)
    assert note["surface"] == "overall" and note["date"] == when
    # A real pooled move inside the window is reported as withheld, not as a drop.
    _answers(db_session, t, run, n=60, named=42, days_ago=20)
    _answers(db_session, t, run, n=60, named=12, days_ago=3)
    kinds = {a["kind"] for a in alerts(db_session, t.id)}
    assert "series_break" in kinds


def test_admin_can_set_and_reset_weights(client, login, db_session):
    t, _run = _tenant(db_session)
    admin = User(email="admin@example.com", clerk_user_id="u_admin", is_superadmin=True)
    db_session.add(admin)
    db_session.commit()
    login(admin)
    assert client.get("/api/admin/engine-weights").json()["defaults"] == DEFAULT_ENGINE_WEIGHTS
    bad = client.patch(f"/api/admin/tenants/{t.slug}", json={"engine_weights": {"nope": 5}})
    assert bad.status_code == 422
    ok = client.patch(f"/api/admin/tenants/{t.slug}", json={"engine_weights": {"claude": 25}})
    assert ok.status_code == 200
    db_session.refresh(t)
    assert t.engine_weights == {"claude": 25} and t.engine_weights_changed_on
    reset = client.patch(f"/api/admin/tenants/{t.slug}", json={"engine_weights": {}})
    assert reset.status_code == 200
    db_session.refresh(t)
    assert t.engine_weights is None
