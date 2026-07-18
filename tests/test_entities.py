"""Open out-of-list entity extraction (step 4): the pure prompt/parse/filter,
the governed router's message parser, and the governed processing integration
(router monkeypatched — CI never calls a live LLM)."""

import pytest

from engine.llm.policy import ModelPolicyViolation
from engine.llm.router import parse_message_text
from engine.processing.entities import filter_untracked, parse_entities


def test_parse_entities_tolerates_fences_and_prose():
    assert parse_entities('```json\n["Square", "Toast"]\n```') == ["Square", "Toast"]
    assert parse_entities('Here you go: ["Wix", "Wix"]') == ["Wix"]  # de-duped
    assert parse_entities("no array here") == []
    assert parse_entities("") == []
    assert parse_entities("[not, valid, json]") == []


def test_filter_untracked_drops_tracked_by_containment():
    names = ["GoDaddy", "GoDaddy.com", "Square", "Toast", "Wix"]
    tracked = ["GoDaddy", "Wix"]
    assert filter_untracked(names, tracked) == ["Square", "Toast"]


def test_router_parse_message_text_is_null_safe():
    assert parse_message_text({"content": None}) == ""
    assert parse_message_text(
        {"content": [{"type": "text", "text": "["}, {"type": "text", "text": "]"}]}
    ) == "[]"
    # non-text blocks ignored
    assert parse_message_text({"content": [{"type": "tool_use"}]}) == ""


def test_router_rejects_disallowed_model_before_network():
    from engine.llm import router

    with pytest.raises(ModelPolicyViolation):
        router.complete("hi", model="claude-fable-5", api_key="sk-x")


def test_processing_extracts_untracked_when_enabled(db_session, monkeypatch):
    from sqlmodel import select

    from api.models import (
        BrandProfile,
        Competitor,
        Result,
        ResultStatus,
        ResultVariant,
        Run,
        RunStatus,
        SurfaceCode,
        Tenant,
        UntrackedMention,
    )
    from api.processing_service import process_run

    tenant = Tenant(
        name="GoDaddy", slug="gd",
        ai_processing_approved=True,
        entity_extraction_enabled=True,
        approved_utility_models=["claude-haiku-4-5-20251001"],
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db_session.add(Competitor(tenant_id=tenant.id, name="Wix", aliases=[], domains=["wix.com"]))
    db_session.commit()

    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    r = Result(
        run_id=run.id, tenant_id=tenant.id, query_text="best hosting for a restaurant",
        persona_name="p", persona_segment="new_entrepreneur",
        surface=SurfaceCode.openai_api, variant=ResultVariant.search,
        status=ResultStatus.ok, raw_uri="inline",
    )
    db_session.add(r)
    db_session.commit()

    # Answer text comes from the raw envelope; stub it and the API key + router.
    monkeypatch.setattr(
        "api.processing_service._response_text",
        lambda result, session: "Try GoDaddy, Wix, Square, or Toast.",
    )
    from api.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    monkeypatch.setattr(
        "engine.llm.router.complete",
        lambda *a, **k: '["GoDaddy", "Wix", "Square", "Toast"]',
    )

    counts = process_run(db_session, run)
    assert counts["untracked_mentions"] == 2  # GoDaddy + Wix filtered, Square + Toast kept
    names = {
        u.entity_name
        for u in db_session.exec(
            select(UntrackedMention).where(UntrackedMention.tenant_id == tenant.id)
        ).all()
    }
    assert names == {"Square", "Toast"}


def test_processing_skips_extraction_when_disabled(db_session, monkeypatch):
    from api.models import (
        BrandProfile,
        Result,
        ResultStatus,
        ResultVariant,
        Run,
        RunStatus,
        SurfaceCode,
        Tenant,
    )
    from api.processing_service import process_run

    tenant = Tenant(name="Smith", slug="smith")  # extraction off by default
    db_session.add(tenant)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="Smith", domains=["s.ca"]))
    db_session.commit()
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    db_session.add(Result(
        run_id=run.id, tenant_id=tenant.id, query_text="q", persona_name="p",
        surface=SurfaceCode.openai_api, variant=ResultVariant.search,
        status=ResultStatus.ok, raw_uri="inline",
    ))
    db_session.commit()

    # If extraction ran, this would raise — proving it's a hard no-op.
    def _boom(*a, **k):
        raise AssertionError("router must not be called when extraction is disabled")

    monkeypatch.setattr("engine.llm.router.complete", _boom)
    monkeypatch.setattr(
        "api.processing_service._response_text", lambda result, session: "GoDaddy and Wix"
    )
    counts = process_run(db_session, run)
    assert counts["untracked_mentions"] == 0


def test_whitespace_report_ranks_untracked_by_frequency(db_session):
    from api.dashboards_service import whitespace_report
    from api.models import (
        BrandProfile,
        Result,
        ResultStatus,
        ResultVariant,
        Run,
        RunStatus,
        SurfaceCode,
        Tenant,
        UntrackedMention,
    )

    tenant = Tenant(name="GoDaddy", slug="gd")
    db_session.add(tenant)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db_session.commit()
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    def _result(seg, surface):
        r = Result(
            run_id=run.id, tenant_id=tenant.id, query_text="q", persona_name="p",
            persona_segment=seg, surface=SurfaceCode(surface),
            variant=ResultVariant.search, status=ResultStatus.ok,
        )
        db_session.add(r)
        db_session.commit()
        db_session.refresh(r)
        return r

    r1 = _result("new_entrepreneur", "openai_api")
    r2 = _result("side_hustler", "copilot_web")
    for rid, name in [(r1.id, "Square"), (r2.id, "Square"), (r1.id, "Toast")]:
        db_session.add(UntrackedMention(result_id=rid, tenant_id=tenant.id, entity_name=name))
    db_session.commit()

    rep = whitespace_report(db_session, tenant.id)
    assert rep["observed"] is True
    top = rep["entities"][0]
    assert top["name"] == "Square" and top["count"] == 2  # ranked by frequency
    assert set(top["segments"]) == {"new_entrepreneur", "side_hustler"}
    assert "Microsoft Copilot" in top["engines"]
