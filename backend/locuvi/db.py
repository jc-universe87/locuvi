"""SQLite engine/session setup (WAL, busy timeout, explicit BEGIN control)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        # Take over transaction control from pysqlite so BEGIN IMMEDIATE works.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # type: ignore[no-untyped-def]
        if conn.get_execution_options().get("sqlite_immediate"):
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.exec_driver_sql("BEGIN")

    return engine


def init_engine(db_path: Path) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(db_path)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("database not initialised")
    return _engine


def new_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("database not initialised")
    return _SessionLocal()


@contextmanager
def immediate_session() -> Iterator[Session]:
    """A session whose transaction starts with BEGIN IMMEDIATE (write lock up front).

    Used for invoice issue so that number allocation is serialised across
    threads and processes.
    """
    engine = get_engine()
    with engine.connect().execution_options(sqlite_immediate=True) as conn:
        session = Session(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
