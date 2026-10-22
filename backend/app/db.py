from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class DatabaseNotConfiguredError(RuntimeError):
    pass


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, future=True)


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Copy backend/.env.example to backend/.env "
            "(or run `make setup`) and make sure PostgreSQL is running (`make db`)."
        )
    return make_engine(url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
