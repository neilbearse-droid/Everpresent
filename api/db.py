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
        url = normalize_db_url(get_settings().database_url)
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            # Managed Postgres drops idle/old connections; recycle before they
            # go stale and keep the socket alive during quiet stretches. The
            # jobs also avoid holding a connection across slow provider calls.
            kwargs["pool_recycle"] = 280
            kwargs["connect_args"] = {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
        _engine = create_engine(url, **kwargs)
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
