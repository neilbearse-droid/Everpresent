"""Content-gen closed loop (step 5): the pure draft prompt/parse, and the
governed generation service (router monkeypatched — CI never calls a live LLM)."""

import pytest

from engine.content.draft import (
    AccuracyGapContext,
    build_accuracy_draft_prompt,
    parse_draft,
)


def test_parse_draft_reads_json_object():
    title, body = parse_draft('```json\n{"title": "T", "body": "# Body"}\n```')
    assert title == "T" and body == "# Body"


def test_parse_draft_falls_back_to_raw_when_not_json():
    title, body = parse_draft("Just some prose, no JSON.")
    assert title == "" and body == "Just some prose, no JSON."
    assert parse_draft("") == ("", "")


def test_build_prompt_includes_correction_and_sources():
    ctx = AccuracyGapContext(
        brand_name="GoDaddy",
        subject="domain privacy",
        wrong_claim="domain privacy is free",
        correct_value="Domain privacy is a paid add-on",
        engines=["ChatGPT", "Microsoft Copilot"],
        snippets=["GoDaddy offers free domain privacy."],
        source_domains=["reddit.com", "someaffiliate.com"],
    )
    prompt = build_accuracy_draft_prompt(ctx)
    assert "domain privacy is free" in prompt
    assert "Domain privacy is a paid add-on" in prompt
    assert "reddit.com" in prompt
    assert "ChatGPT" in prompt


def _seed_tenant(db, **flags):
    from api.models import BrandFact, BrandProfile, Tenant

    tenant = Tenant(name="GoDaddy", slug="gd", **flags)
    db.add(tenant)
    db.commit()
    db.add(BrandProfile(tenant_id=tenant.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    fact = BrandFact(
        tenant_id=tenant.id, category="pricing", label="Domain privacy is a paid add-on",
        subject="domain privacy", kind="disallowed", expected="domain privacy is free",
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return tenant, fact


def test_generate_requires_governance(db_session):
    from api.content_service import ContentGenUnavailable, generate_accuracy_draft

    tenant, fact = _seed_tenant(db_session)  # not approved
    with pytest.raises(ContentGenUnavailable):
        generate_accuracy_draft(db_session, tenant, fact.id)


def test_generate_accuracy_draft_is_idempotent(db_session, monkeypatch):
    from sqlmodel import select

    from api.config import get_settings
    from api.content_service import generate_accuracy_draft
    from api.models import ContentDraft

    tenant, fact = _seed_tenant(
        db_session,
        ai_processing_approved=True,
        approved_utility_models=["claude-sonnet-4-6"],
    )
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    _reply = '{"title": "Domain privacy pricing, explained", "body": "It is a paid add-on."}'
    monkeypatch.setattr("engine.llm.router.complete", lambda *a, **k: _reply)

    d1 = generate_accuracy_draft(db_session, tenant, fact.id)
    assert d1.title == "Domain privacy pricing, explained"
    assert "paid add-on" in d1.body
    assert d1.source_ref == f"fact:{fact.id}"

    # Regenerating replaces, not duplicates.
    d2 = generate_accuracy_draft(db_session, tenant, fact.id)
    assert d2.id == d1.id
    drafts = db_session.exec(
        select(ContentDraft).where(ContentDraft.tenant_id == tenant.id)
    ).all()
    assert len(drafts) == 1
