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
    # Skip lifespan init_db (would hit the real DATABASE_URL engine).
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
