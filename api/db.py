from collections.abc import Iterator

from sqlmodel import Session, create_engine

from api.config import get_settings

_engine = None


def normalize_db_url(url: str) -> str:
    """Managed platforms (Render, Heroku, Railway) hand out DATABASE_URL as
    `postgres://` or `postgresql://`, which SQLAlchemy routes to the psycopg2
    driver we don't install. Rewrite to the psycopg (v3) driver we do."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            normalize_db_url(get_settings().database_url), pool_pre_ping=True
        )
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
