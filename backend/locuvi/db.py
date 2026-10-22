"""SQLite engine/session setup (WAL, busy timeout, explicit BEGIN control).

Each household profile has its own database. The profile in effect is a context variable:
the web middleware sets it from the signed-in session, background threads set it per
profile, and everything that calls ``new_session()``/``get_engine()`` then works on that
profile's data only. Profile 1 (the original installation) is the default.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_engines: dict[int, tuple[Engine, sessionmaker[Session]]] = {}
_engines_lock = threading.Lock()
_current: ContextVar[int] = ContextVar("locuvi_profile", default=1)


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


def init_engine(db_path: Path, profile_id: int = 1) -> Engine:
    """Open (or reopen) the database of one profile; profile 1 by default."""
    with _engines_lock:
        old = _engines.pop(profile_id, None)
        if old is not None:
            old[0].dispose()
        engine = make_engine(db_path)
        _engines[profile_id] = (engine, sessionmaker(bind=engine, expire_on_commit=False))
    return engine


def close_profile(profile_id: int) -> None:
    with _engines_lock:
        old = _engines.pop(profile_id, None)
    if old is not None:
        old[0].dispose()


def current_profile() -> int:
    return _current.get()


def set_profile(profile_id: int) -> None:
    """Switch this thread/task to a profile (used at the start of a request or job)."""
    _current.set(profile_id)


@contextmanager
def use_profile(profile_id: int) -> Iterator[None]:
    token = _current.set(profile_id)
    try:
        yield
    finally:
        _current.reset(token)


def _pair() -> tuple[Engine, sessionmaker[Session]]:
    pair = _engines.get(_current.get())
    if pair is None:
        raise RuntimeError("database not initialised")
    return pair


def get_engine() -> Engine:
    return _pair()[0]


def new_session() -> Session:
    return _pair()[1]()


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


def end_read(s: Session) -> None:
    """End a transaction that has only read, so the next write starts a fresh one.

    In WAL mode SQLite can't turn a read into a write once another connection has written
    since the read began: it fails at once with "database is locked" instead of waiting.
    Call this between slow work (saving a file, reading a PDF) and the writes that follow.
    """
    if not (s.new or s.dirty or s.deleted or s.info.get("wrote")):
        s.rollback()


@event.listens_for(Session, "after_flush")
def _wrote(s: Session, _ctx) -> None:  # type: ignore[no-untyped-def]
    s.info["wrote"] = True  # this transaction has written, so end_read must keep it


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _ended(s: Session) -> None:
    s.info.pop("wrote", None)


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()
