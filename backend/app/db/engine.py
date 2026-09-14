"""SQLAlchemy 2.x engine. SQLite file-based; URL comes from settings."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@event.listens_for(Engine, "connect")
def _enable_sqlite_fks(dbapi_connection, _connection_record) -> None:
    module = getattr(dbapi_connection, "__class__", type("x", (), {})).__module__
    if "sqlite" not in module:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _connect_args(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine(url: str | None = None) -> Engine:
    settings = get_settings()
    db_url = url or settings.db_url
    return create_engine(db_url, connect_args=_connect_args(db_url), echo=False)


engine = get_engine()
