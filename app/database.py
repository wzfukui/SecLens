"""Database engine and session handling utilities."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    """Create (or return cached) SQLAlchemy engine configured from settings."""

    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(settings.database_url, echo=False, future=True, connect_args=connect_args)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return session factory bound to the configured engine."""

    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    return _SessionLocal


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependencies."""

    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


__all__ = ["Base", "get_engine", "get_session_factory", "get_db_session"]
