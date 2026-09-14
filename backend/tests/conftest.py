"""Shared pytest fixtures."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import get_engine
from app.db.seed import list_worlds, seed_world
from app.main import app

WORLD_NAMES = list_worlds()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def open_seeded_session(db_path: Path, world: str) -> Session:
    engine = get_engine(f"sqlite:///{db_path}")
    seed_world(world, engine=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


@pytest.fixture
def seeded_base(tmp_path: Path) -> Generator[Session, None, None]:
    session = open_seeded_session(tmp_path / "base.db", "base")
    try:
        yield session
    finally:
        session.close()
