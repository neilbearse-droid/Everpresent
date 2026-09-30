import os

# Tests never touch Postgres or Clerk. Set before any api import.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CLERK_SECRET_KEY"] = ""
os.environ["CLERK_JWKS_URL"] = ""

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# CI's Postgres job sets TEST_DATABASE_URL to a database built by
# `alembic upgrade head` — so the suite runs against the MIGRATED schema, and a
# migration that drifts from the models (e.g. a native-enum value never added)
# fails here instead of in production. Unset, tests use in-memory SQLite.
_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_pg_engine = None


def _postgres_engine():
    global _pg_engine
    if _pg_engine is None:
        from api.db import normalize_db_url

        _pg_engine = create_engine(normalize_db_url(_PG_URL))
    return _pg_engine


@pytest.fixture()
def db_session():
    import api.models  # noqa: F401

    if _PG_URL:
        engine = _postgres_engine()
        with Session(engine) as session:
            yield session
            session.rollback()
        tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
        with engine.begin() as conn:
            conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
        return

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
