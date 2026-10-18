from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from ..config import database_url


_ENGINE: Engine | None = None


def engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(database_url(), pool_pre_ping=True, future=True)
    return _ENGINE


@contextmanager
def transaction() -> Iterator[Connection]:
    with engine().begin() as conn:
        yield conn


def health_check() -> dict[str, object]:
    with engine().connect() as conn:
        value = conn.execute(text("SELECT 1")).scalar_one()
    return {"database": "postgresql", "ok": value == 1}


def reset_engine_for_tests() -> None:
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
