"""SQLAlchemy 2.x engine. SQLite file-based; URL comes from settings."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _connect_args(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    db_url = url or settings.db_url
    return create_engine(db_url, connect_args=_connect_args(db_url), echo=False)


engine = get_engine()
