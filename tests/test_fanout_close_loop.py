"""Fan-out close-the-loop (§FANOUT_SCORECARD M25c): a corrective brief per lost
shard through the governed draft model, and trend deltas (won back / newly
lost) against each shard's previous re-probe."""

import pytest
from sqlmodel import select

from api.models import ContentDraft, FanoutShard
from engine.content.draft import ShardGapContext, build_shard_draft_prompt
from engine.retrievers.openai_api import ParsedResponse, RetrievalOutcome
from tests.test_fanout_reprobe import _run, _shards, _tenant, env  # noqa: F401


def test_shard_prompt_carries_the_contest():
    prompt = build_shard_draft_prompt(ShardGapContext(
        brand_name="GoDaddy", parent_query="best domain registrar",
        shard_text="namecheap vs porkbun", winners=["Namecheap"], engine="Gemini",
        snippets=["Namecheap wins here."], source_domains=["namecheap.com"],
    ))
    for needle in ("namecheap vs porkbun", "best domain registrar", "Namecheap",
                   "namecheap.com", "Gemini", "[placeholders]"):
        assert needle in prompt


def _governed(db, tenant, monkeypatch, prompts):
    from api.config import get_settings

    tenant.ai_processing_approved = True
    tenant.approved_utility_models = [get_settings().utility_model_draft]
    db.add(tenant)
    db.commit()
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")

    def _complete(prompt, **_kw):
        prompts.append(prompt)
        return '{"title": "Namecheap vs Porkbun — and where GoDaddy fits", "body": "## Answer"}'

    monkeypatch.setattr("engine.llm.router.complete", _complete)


def _probed(db, env, tenant):  # noqa: F811 — env is the imported fixture
    from worker.jobs import run_fanout_reprobe, run_mode_a

    run_id = _run(db, tenant)
    run_mode_a(run_id)
    run_fanout_reprobe(run_id)
    db.expire_all()
    return run_id


def test_brief_for_a_lost_shard_uses_the_probe_answer(db_session, env, monkeypatch):  # noqa: F811
    from api.content_service import generate_shard_draft

    tenant = _tenant(db_session)
    run_id = _probed(db_session, env, tenant)
    prompts: list[str] = []
    _governed(db_session, tenant, monkeypatch, prompts)

    lost = _shards(db_session, run_id)["namecheap vs porkbun"]
    assert lost.priority == "high"
    draft = generate_shard_draft(db_session, tenant, lost.id)  # type: ignore[arg-type]
    assert draft.source_kind == "fanout"
    assert draft.source_ref == "shard:namecheap vs porkbun"
    assert draft.title.startswith("Namecheap vs Porkbun")
    # Context comes from the re-probe answer: who won, how, and what it cited.
    assert "Namecheap wins here." in prompts[0]
    assert "namecheap.com" in prompts[0]
    assert "Gemini" in prompts[0]

    # The same shard in a later run shares the draft (keyed by shard text).
    from worker.jobs import run_mode_a

    second = _run(db_session, tenant)
    run_mode_a(second)
    db_session.expire_all()
    carried = _shards(db_session, second)["namecheap vs porkbun"]
    assert carried.id != lost.id and carried.source == "reprobed"
    again = generate_shard_draft(db_session, tenant, carried.id)  # type: ignore[arg-type]
    assert again.id == draft.id
    assert len(db_session.exec(
        select(ContentDraft).where(ContentDraft.tenant_id == tenant.id)
    ).all()) == 1


def test_brief_refused_without_a_measured_miss(db_session, env, monkeypatch):  # noqa: F811
    from api.content_service import ContentGenUnavailable, generate_shard_draft

    tenant = _tenant(db_session)
    run_id = _probed(db_session, env, tenant)
    shards = _shards(db_session, run_id)

    # Governance first: draft model not on the allowlist → refused even for a
    # real miss.
    with pytest.raises(ContentGenUnavailable, match="approved utility models"):
        generate_shard_draft(db_session, tenant, shards["namecheap vs porkbun"].id)  # type: ignore[arg-type]

    _governed(db_session, tenant, monkeypatch, [])
    unresolved = next(s for s in shards.values() if s.source == "unresolved")
    with pytest.raises(ContentGenUnavailable, match="absent"):
        generate_shard_draft(db_session, tenant, unresolved.id)  # type: ignore[arg-type]
    with pytest.raises(ContentGenUnavailable, match="no such shard"):
        generate_shard_draft(db_session, tenant, 999_999)


def _flip_winner_to_brand(monkeypatch, probes):
    """Second-round answers: the brand now shows up on the namecheap shard."""
    from tests.test_fanout_reprobe import _fake_for

    for surface in ("openai_api", "gemini_api"):
        base = _fake_for(surface, probes)

        async def _fake(persona_prompt, query_text, *, _base=base, **kw):
            outcome = await _base(persona_prompt, query_text, **kw)
            if "namecheap" in query_text:
                return RetrievalOutcome(
                    payload=outcome.payload,
                    parsed=ParsedResponse(
                        text="GoDaddy and Namecheap both work.", model=outcome.parsed.model,
                        input_tokens=100, output_tokens=50, web_search_calls=1,
                    ),
                    latency_ms=5,
                )
            return outcome

        monkeypatch.setattr(f"engine.retrievers.{surface}.retrieve", _fake)


def test_scorecard_trend_won_back_and_steady(db_session, env, monkeypatch):  # noqa: F811
    from api.config import get_settings
    from api.dashboards_service import fanout_scorecard

    tenant = _tenant(db_session)
    _probed(db_session, env, tenant)
    card = fanout_scorecard(db_session, tenant.id)  # type: ignore[arg-type]
    # First measurement: nothing to compare against yet.
    assert all(s["trend"] is None for s in card["prompts"][0]["shards"])

    # Force a fresh re-probe next run (no carry-forward) with a changed answer.
    monkeypatch.setattr(get_settings(), "fanout_reprobe_ttl_days", 0)
    _flip_winner_to_brand(monkeypatch, env["probes"])
    _probed(db_session, env, tenant)

    card = fanout_scorecard(db_session, tenant.id)  # type: ignore[arg-type]
    by_text = {s["text"]: s for s in card["prompts"][0]["shards"]}
    assert by_text["namecheap vs porkbun"]["brand_present"] is True
    assert by_text["namecheap vs porkbun"]["trend"] == "won_back"
    assert by_text["cheap domain registrar"]["trend"] == "steady"
    assert card["trend"] == {"won_back": 1, "lost": 0}
    assert card["prompts"][0]["won_back"] == 1

    # Two distinct measurements exist; carried copies would not add points.
    oks = db_session.exec(
        select(FanoutShard).where(
            FanoutShard.shard_norm == "namecheap vs porkbun", FanoutShard.probe_status == "ok"
        )
    ).all()
    assert len(oks) == 2
