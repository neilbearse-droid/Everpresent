from sqlmodel import select

from api.models import User


def test_seed_creates_and_is_idempotent(db_session, monkeypatch):
    import api.seed as seed_mod

    monkeypatch.setattr(seed_mod, "init_db", lambda: None)
    monkeypatch.setattr(seed_mod, "get_engine", lambda: db_session.get_bind())
    monkeypatch.setenv("SUPERADMIN_EMAIL", "neil@example.com")
    from api.config import get_settings

    get_settings.cache_clear()

    first = seed_mod.seed()
    assert "Seeded superadmin" in first
    second = seed_mod.seed()
    assert "already present" in second

    users = db_session.exec(select(User).where(User.email == "neil@example.com")).all()
    assert len(users) == 1
    assert users[0].is_superadmin

    get_settings.cache_clear()
