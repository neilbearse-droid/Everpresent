"""Fan-out re-probe (§FANOUT_SCORECARD M25b): harvest shards from a run, pick the
top ones under the plan's K + per-run ceiling + spend cap, re-run each on an
engine that issued it, and record honest per-shard presence. Shard probes must
never leak into competitive aggregations, and no cap is silent."""

import inspect

import pytest
from sqlmodel import Session, select

from api.fanout_service import (
    ShardCandidate,
    evaluate_probe,
    probe_surface_for,
    select_candidates,
    shard_norm,
    shard_priority,
)
from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    FanoutShard,
    Mention,
    Persona,
    Query,
    Result,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
    VisibilityDaily,
)
from engine.retrievers.openai_api import ParsedCitation, ParsedResponse, RetrievalOutcome

# ---------------------------------------------------------------- pure logic


def _cand(i, parent, *, reach=1, absent=True, rival=False, names_brand=False):
    return ShardCandidate(
        shard_id=i, parent=parent, text=f"shard {i}", reach=reach,
        parent_brand_absent=absent, shard_names_rival=rival, parent_names_rival=False,
        names_brand=names_brand,
    )


def test_select_candidates_applies_k_then_ceiling_and_reports_drops():
    cands = [
        _cand(1, "a", reach=2, rival=True),   # best in a
        _cand(2, "a", rival=True),
        _cand(3, "a", names_brand=True),      # navigational — ranks last
        _cand(4, "b", reach=2, rival=True),
        _cand(5, "b", absent=False),
    ]
    chosen, dropped_k, dropped_ceiling = select_candidates(cands, per_prompt=2, per_run=3)
    assert [c.shard_id for c in dropped_k] == [3]
    assert [c.shard_id for c in chosen] == [1, 4, 2]
    assert [c.shard_id for c in dropped_ceiling] == [5]

    chosen, _dk, dropped_ceiling = select_candidates(cands, per_prompt=2, per_run=2)
    assert [c.shard_id for c in chosen] == [1, 4]
    assert [c.shard_id for c in dropped_ceiling] == [2, 5]


def test_select_candidates_zero_k_probes_nothing():
    chosen, dropped_k, _ = select_candidates([_cand(1, "a")], per_prompt=0, per_run=10)
    assert chosen == [] and [c.shard_id for c in dropped_k] == [1]


def test_priority_bands():
    assert shard_priority(None, ["X"]) == ""  # unresolved: no claim
    assert shard_priority(False, ["Namecheap"]) == "high"
    assert shard_priority(False, []) == "med"
    assert shard_priority(True, ["Namecheap"]) == "low"


def test_probe_surface_prefers_cheapest_issuing_engine():
    both = ["gemini_api", "openai_api"]
    assert probe_surface_for(both, {"openai_api", "gemini_api"}) == "openai_api"
    assert probe_surface_for(both, {"gemini_api"}) == "gemini_api"
    # Never probe on an engine that didn't issue the shard.
    assert probe_surface_for(["gemini_api"], {"openai_api"}) is None


def test_evaluate_probe_uses_mentions_and_owned_domains():
    comps = [(1, "Namecheap", ["NC"], ["namecheap.com"]), (2, "Wix", [], ["wix.com"])]
    kw = dict(brand_name="GoDaddy", brand_aliases=[], brand_domains=["godaddy.com"],
              competitors=comps)
    present, winners = evaluate_probe("Namecheap is cheapest.", ["wix.com"], **kw)
    assert present is False and winners == ["Namecheap", "Wix"]
    present, winners = evaluate_probe("Options vary.", ["www.godaddy.com"], **kw)
    assert present is True and winners == []


def test_shard_norm_collapses_case_and_space():
    assert shard_norm("  Cheap   Domain  Registrar ") == "cheap domain registrar"


# ---------------------------------------------------------------- pipeline

BRAND_ANSWER = "Namecheap and GoDaddy are both popular."
FANOUT = {
    "openai_api": ["cheap domain registrar", "Best Domain Registrar"],
    "gemini_api": ["Cheap  domain registrar", "domain registrar with free privacy",
                   "namecheap vs porkbun", "registrar transfer fees"],
}


def _tenant(db: Session, *, plan="diagnose", enabled=True, cap=50.0) -> Tenant:
    t = Tenant(
        name="GoDaddy", slug="godaddy", ai_processing_approved=True,
        approved_surfaces=["openai_api", "gemini_api"], plan=plan,
        fanout_reprobe_enabled=enabled, monthly_spend_cap_usd=cap,
    )
    db.add(t)
    db.commit()
    assert t.id is not None
    for code in ("openai_api", "gemini_api"):
        db.add(TenantSurface(tenant_id=t.id, code=SurfaceCode(code), enabled=True))
    db.add(BrandProfile(tenant_id=t.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db.add(Competitor(tenant_id=t.id, name="Namecheap", domains=["namecheap.com"]))
    db.add(Query(tenant_id=t.id, text="best domain registrar"))
    db.add(Query(tenant_id=t.id, text="GoDaddy review", branded=True))
    db.add(Persona(tenant_id=t.id, name="buyer", prompt_text="You buy domains.",
                   segment_tag="generic"))
    db.commit()
    return t


def _fake_for(surface: str, probes: list):
    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s,
                    web_search=True, force_search=True):
        is_parent = query_text in ("best domain registrar", "GoDaddy review")
        if not is_parent:
            probes.append((surface, query_text))
        if is_parent:
            text, cites = BRAND_ANSWER, []
            fan = list(FANOUT[surface]) + ["GoDaddy promo code"] * (query_text == "GoDaddy review")
        elif "privacy" in query_text:
            text, cites = "GoDaddy includes privacy.", []
        elif "namecheap" in query_text:
            text, cites = "Namecheap wins here.", [ParsedCitation(url="https://namecheap.com/x")]
        else:
            text, cites = "Porkbun is cheap.", []
        return RetrievalOutcome(
            payload={"surface": surface},
            parsed=ParsedResponse(
                text=text, citations=cites, input_tokens=100, output_tokens=50,
                web_search_calls=1 if web_search else 0, model=model,
                fanout_queries=fan if is_parent and web_search else [],
            ),
            latency_ms=5,
        )

    return _fake


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    from api.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "k-not-real")
    monkeypatch.setenv("GEMINI_API_KEY", "k-not-real")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())
    probes: list = []
    for surface in ("openai_api", "gemini_api"):
        monkeypatch.setattr(f"engine.retrievers.{surface}.retrieve", _fake_for(surface, probes))
    queued: list[int] = []
    monkeypatch.setattr("api.queue.enqueue_fanout_reprobe", queued.append)
    yield {"probes": probes, "queued": queued}
    get_settings.cache_clear()


def _run(db, tenant) -> int:
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.pending,
              surface_set=["openai_api", "gemini_api"], mode_set=["A"])
    db.add(run)
    db.commit()
    assert run.id is not None
    return run.id


def _shards(db, run_id) -> dict[str, FanoutShard]:
    return {
        s.shard_norm: s
        for s in db.exec(select(FanoutShard).where(FanoutShard.run_id == run_id)).all()
    }


def test_harvest_dedups_excludes_parent_and_branded(db_session, env):
    from worker.jobs import run_mode_a

    tenant = _tenant(db_session, enabled=False)
    run_id = _run(db_session, tenant)
    run_mode_a(run_id)

    shards = _shards(db_session, run_id)
    assert set(shards) == {
        "cheap domain registrar", "domain registrar with free privacy",
        "namecheap vs porkbun", "registrar transfer fees",
    }  # parent echo + branded prompt's shard excluded; whitespace/case deduped
    assert shards["cheap domain registrar"].issuing_surfaces == ["gemini_api", "openai_api"]
    assert shards["cheap domain registrar"].reach == 2
    assert all(s.source == "unresolved" and s.priority == "" for s in shards.values())
    # Opt-out tenant: nothing queued, nothing probed.
    assert env["queued"] == [] and env["probes"] == []

    # Reprocess is idempotent (updates in place, no duplicates).
    from api.processing_service import process_run

    run = db_session.get(Run, run_id)
    assert run is not None
    process_run(db_session, run)
    assert len(_shards(db_session, run_id)) == 4


def test_reprobe_end_to_end(db_session, env):
    from api.dashboards_service import fanout_scorecard
    from worker.jobs import run_fanout_reprobe, run_mode_a

    tenant = _tenant(db_session)  # diagnose: K=2 per prompt, 15 per run
    run_id = _run(db_session, tenant)
    run_mode_a(run_id)
    assert env["queued"] == [run_id]
    cost_before = db_session.get(Run, run_id).cost_usd  # type: ignore[union-attr]

    run_fanout_reprobe(run_id)
    db_session.expire_all()

    shards = _shards(db_session, run_id)
    reprobed = {k: s for k, s in shards.items() if s.source == "reprobed"}
    assert len(reprobed) == 2  # K=2 for the one competitive prompt
    dropped = [s for s in shards.values() if s.source == "unresolved"]
    assert {s.probe_status for s in dropped} == {"dropped_k"}  # never silent

    # Highest reach wins a slot, and shards probe only on an issuing engine,
    # cheapest first.
    cheap = shards["cheap domain registrar"]
    assert cheap.source == "reprobed" and cheap.probe_surface == "openai_api"
    for s in reprobed.values():
        assert s.probe_surface in s.issuing_surfaces
    # Competitor-named shard outranks the unnamed ones.
    nvp = shards["namecheap vs porkbun"]
    assert nvp.source == "reprobed" and nvp.probe_surface == "gemini_api"
    assert nvp.brand_present is False and nvp.winners == ["Namecheap"]
    assert nvp.priority == "high"
    assert cheap.brand_present is False and cheap.winners == [] and cheap.priority == "med"

    run = db_session.get(Run, run_id)
    assert run is not None and run.status == RunStatus.complete
    assert run.counts["fanout_reprobed"] == 2
    assert run.counts["fanout_dropped_k"] == 2
    assert run.cost_usd > cost_before  # probe spend accrues to the monthly cap

    # Probe results are stored as variant=shard with NO mention/citation rows.
    probe_rows = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.variant == ResultVariant.shard)
    ).all()
    assert len(probe_rows) == 2
    ids = [r.id for r in probe_rows]
    assert not db_session.exec(select(Mention).where(Mention.result_id.in_(ids))).all()  # pyright: ignore[reportAttributeAccessIssue]
    assert not db_session.exec(select(Citation).where(Citation.result_id.in_(ids))).all()  # pyright: ignore[reportAttributeAccessIssue]

    card = fanout_scorecard(db_session, tenant.id)  # type: ignore[arg-type]
    assert card["coverage"] == {"reprobed": 2, "unresolved": 2}
    assert card["reprobe_enabled"] is True
    p = card["prompts"][0]
    assert (p["shards_present"], p["shards_absent"], p["high_misses"]) == (0, 2, 1)
    assert p["shards"][0]["text"] == "namecheap vs porkbun"  # HIGH sorts first
    assert p["shards"][0]["probe_engine"] == "Gemini"
    unresolved = [s for s in p["shards"] if s["source"] == "unresolved"]
    assert all(s["brand_present"] is None and s["priority"] == "" for s in unresolved)
    assert {s["probe_status"] for s in unresolved} == {"dropped_k"}


def test_fresh_reprobe_carries_forward_instead_of_rebuying(db_session, env):
    from worker.jobs import run_fanout_reprobe, run_mode_a

    tenant = _tenant(db_session)
    first = _run(db_session, tenant)
    run_mode_a(first)
    run_fanout_reprobe(first)
    probes_after_first = len(env["probes"])

    second = _run(db_session, tenant)
    run_mode_a(second)
    db_session.expire_all()
    carried = [s for s in _shards(db_session, second).values() if s.probe_status == "carried"]
    assert len(carried) == 2 and all(s.source == "reprobed" for s in carried)

    run_fanout_reprobe(second)
    # The two already-measured shards aren't re-bought; the other two get their turn.
    assert len(env["probes"]) == probes_after_first + 2
    db_session.expire_all()
    assert all(s.source == "reprobed" for s in _shards(db_session, second).values())


def test_spend_cap_withholds_and_records(db_session, env):
    from worker.jobs import run_fanout_reprobe, run_mode_a

    tenant = _tenant(db_session)
    run_id = _run(db_session, tenant)
    run_mode_a(run_id)
    # Tighten the cap to exactly what's been spent: every probe is withheld.
    run = db_session.get(Run, run_id)
    assert run is not None
    tenant.monthly_spend_cap_usd = run.cost_usd
    db_session.add(tenant)
    db_session.commit()

    run_fanout_reprobe(run_id)
    db_session.expire_all()
    statuses = sorted(s.probe_status for s in _shards(db_session, run_id).values())
    assert statuses == ["dropped_k", "dropped_k", "withheld_cap", "withheld_cap"]
    run = db_session.get(Run, run_id)
    assert run is not None
    assert run.counts["fanout_withheld_by_cap"] == 2 and run.counts["fanout_reprobe_capped"] == 1
    assert env["probes"] == []


def test_map_only_plan_never_queues_or_probes(db_session, env):
    from worker.jobs import run_fanout_reprobe, run_mode_a

    tenant = _tenant(db_session, plan="monitor")  # K = 0
    run_id = _run(db_session, tenant)
    run_mode_a(run_id)
    assert env["queued"] == []
    run_fanout_reprobe(run_id)  # a stray job is a no-op
    assert env["probes"] == []


def test_shard_probes_never_reach_competitive_aggregations(db_session, env):
    """Coupling test (§3.2): shard probes are measurement-only. The rollup, the
    visibility layer, and every other aggregation read search/natural/nosearch
    explicitly, so a shard probe can't change a score."""
    import api.dashboards_service as dashboards
    import api.recommendations_service as recs
    import api.reports as reports
    from api.processing_service import process_run, rollup_day
    from worker.jobs import run_fanout_reprobe, run_mode_a

    for module in (dashboards, recs, reports):
        assert "ResultVariant.shard" not in inspect.getsource(module)

    tenant = _tenant(db_session)
    run_id = _run(db_session, tenant)
    run_mode_a(run_id)

    def snapshot():
        return sorted(
            (v.surface, v.brand_score, v.extras.get("result_count"))
            for v in db_session.exec(
                select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant.id)
            ).all()
        )

    before = snapshot()
    run_fanout_reprobe(run_id)
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    assert run is not None
    process_run(db_session, run)  # reprocess with shard rows present
    from api.processing_service import _run_day

    rollup_day(db_session, tenant.id, _run_day(run))  # type: ignore[arg-type]
    assert snapshot() == before
    latest = dashboards._latest_results_by_variant(
        db_session, tenant.id, ResultVariant.search  # type: ignore[arg-type]
    )
    assert all(r.variant == ResultVariant.search for r in latest.values())
    # Reprocess kept the probe presence (not wiped back to unresolved).
    assert sum(s.source == "reprobed" for s in _shards(db_session, run_id).values()) == 2


def test_admin_toggles_reprobe(client, db_session, login):
    from api.models import User

    user = User(email="sa@example.com", clerk_user_id="u_sa", is_superadmin=True)
    db_session.add(user)
    db_session.add(Tenant(name="G", slug="g"))
    db_session.commit()
    login(user)
    res = client.patch("/api/admin/tenants/g", json={"fanout_reprobe_enabled": True})
    assert res.status_code == 200 and res.json()["fanout_reprobe_enabled"] is True
