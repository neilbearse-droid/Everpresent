from collections.abc import Iterator

from sqlmodel import Session, create_engine

from api.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
