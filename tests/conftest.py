import os

# Tests never touch Postgres or Clerk. Set before any api import.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CLERK_SECRET_KEY"] = ""
os.environ["CLERK_JWKS_URL"] = ""

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    import api.models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def client(db_session, monkeypatch):
    from fastapi.testclient import TestClient

    from api.db import get_session
    from api.main import app

    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def login(client):
    """Impersonate a user for API calls, bypassing Clerk JWT verification —
    the claims themselves (org_id, org_role) are what's under test."""
    from api.auth import AuthedUser, get_current_user
    from api.main import app

    def _login(user, org_id=None, org_role=None):
        app.dependency_overrides[get_current_user] = lambda: AuthedUser(
            user=user, org_id=org_id, org_role=org_role
        )

    yield _login
    app.dependency_overrides.pop(get_current_user, None)
