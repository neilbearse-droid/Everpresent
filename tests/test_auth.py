"""Org extraction from the Clerk session token. Clerk ships two token shapes
and the server must read the active org from either — a regression here makes
every org-scoped dashboard 403 with 'No organization context in session'."""

from api.auth import _extract_org


def test_legacy_top_level_claims():
    org_id, org_role = _extract_org({"org_id": "org_abc", "org_role": "org:admin"})
    assert org_id == "org_abc"
    assert org_role == "org:admin"


def test_current_nested_o_claim():
    org_id, org_role = _extract_org({"o": {"id": "org_abc", "rol": "admin", "slg": "smith"}})
    assert org_id == "org_abc"
    assert org_role == "admin"


def test_no_org_active():
    org_id, org_role = _extract_org({"sub": "user_1"})
    assert org_id is None
    assert org_role is None


def test_legacy_wins_when_both_present():
    # A token carrying both shapes should still resolve; top-level is read first.
    org_id, _ = _extract_org({"org_id": "org_legacy", "o": {"id": "org_new"}})
    assert org_id == "org_legacy"


def test_first_sign_in_links_the_seeded_superadmin_case_insensitively(db_session, monkeypatch):
    from api.auth import _first_sight
    from api.config import get_settings
    from api.models import User

    db_session.add(User(email="Neil.Bearse@gmail.com", is_superadmin=True))
    db_session.commit()
    monkeypatch.setattr("api.auth._fetch_clerk_email",
                        lambda uid, s: ("neil.bearse@gmail.com", "Neil", True))
    user = _first_sight(db_session, get_settings(), "user_abc")
    assert user.is_superadmin and user.clerk_user_id == "user_abc"


def test_unverified_email_cannot_claim_an_existing_account(db_session, monkeypatch):
    from api.auth import _first_sight
    from api.config import get_settings
    from api.models import User

    db_session.add(User(email="boss@example.com", is_superadmin=True))
    db_session.commit()
    monkeypatch.setattr("api.auth._fetch_clerk_email",
                        lambda uid, s: ("boss@example.com", None, False))
    user = _first_sight(db_session, get_settings(), "user_evil")
    assert not user.is_superadmin
    assert user.email == "user_evil@unknown.invalid"


def test_clerk_outage_still_signs_in(db_session, monkeypatch):
    import httpx

    from api.auth import _fetch_clerk_email, _first_sight
    from api.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_secret_key", "sk_test")

    def _down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("api.auth.httpx.get", _down)
    assert _fetch_clerk_email("user_x", settings) == (None, None, False)
    user = _first_sight(db_session, settings, "user_x")
    assert user.clerk_user_id == "user_x"
