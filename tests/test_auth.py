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
