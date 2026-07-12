from sqlmodel import select

from api.models import Persona, Query, Tenant, User


def test_seed_superadmin_tenants_and_configs(db_session, monkeypatch):
    import api.seed as seed_mod

    monkeypatch.setattr(seed_mod, "get_engine", lambda: db_session.get_bind())
    monkeypatch.setenv("SUPERADMIN_EMAIL", "neil@example.com")
    from api.config import get_settings

    get_settings.cache_clear()

    messages = seed_mod.seed()
    assert any("Seeded superadmin" in m for m in messages)

    users = db_session.exec(select(User).where(User.email == "neil@example.com")).all()
    assert len(users) == 1 and users[0].is_superadmin

    # Both launch tenants exist with imported config (§10 M1).
    for slug in ("smith", "greenshield"):
        tenant = db_session.exec(select(Tenant).where(Tenant.slug == slug)).one()
        assert not tenant.ai_processing_approved  # governance gate defaults closed (§8)
        personas = db_session.exec(select(Persona).where(Persona.tenant_id == tenant.id)).all()
        queries = db_session.exec(select(Query).where(Query.tenant_id == tenant.id)).all()
        assert len(personas) >= 3, slug
        assert len(queries) >= 8, slug

    # Greenshield's early-retirees segment is first-class seed data (§1, §7.1).
    greenshield = db_session.exec(select(Tenant).where(Tenant.slug == "greenshield")).one()
    segments = {
        p.segment_tag
        for p in db_session.exec(select(Persona).where(Persona.tenant_id == greenshield.id)).all()
    }
    assert "early_retirees" in segments

    # Idempotent: second run neither duplicates nor clobbers.
    before = len(db_session.exec(select(Query)).all())
    messages = seed_mod.seed()
    assert any("already present" in m for m in messages)
    assert len(db_session.exec(select(Query)).all()) == before

    get_settings.cache_clear()
