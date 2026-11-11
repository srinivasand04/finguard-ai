from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Used by tests to point the app at a throwaway database."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        yield session


def init_db(drop: bool = False) -> None:
    from app import models  # noqa: F401  (register tables)

    engine = get_engine()
    if drop:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
