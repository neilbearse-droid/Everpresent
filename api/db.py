from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from api.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def init_db() -> None:
    # M0: create_all is sufficient (no data exists yet). Alembic migrations
    # arrive with M1 when the tenancy schema starts carrying real config.
    import api.models  # noqa: F401  (register tables on the metadata)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
