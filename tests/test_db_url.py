"""Managed-platform DATABASE_URL normalization (Render/Heroku/Railway)."""

from api.db import normalize_db_url


def test_rewrites_bare_postgres_scheme():
    assert normalize_db_url("postgres://u:p@host:5432/db") == (
        "postgresql+psycopg://u:p@host:5432/db"
    )


def test_rewrites_postgresql_scheme():
    assert normalize_db_url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"


def test_leaves_explicit_driver_untouched():
    url = "postgresql+psycopg://u:p@host/db"
    assert normalize_db_url(url) == url


def test_leaves_sqlite_untouched():
    assert normalize_db_url("sqlite:///./app.db") == "sqlite:///./app.db"
