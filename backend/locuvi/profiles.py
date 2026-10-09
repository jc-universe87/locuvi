"""Household profiles: each person has their own, fully separate Locuvi.

A profile is a name, a password (scrypt hash) and its own data directory: its own database,
issued PDFs, backups and settings. Nobody can see another profile's data; the admin (the
first profile, created from the existing installation) can only add, rename and remove
profiles and reset their passwords.

The list lives in ``DATA_DIR/profiles.db``. Profile 1 keeps the original data where it always
was (``DATA_DIR`` itself), so upgrading moves no files; later profiles live in
``DATA_DIR/profiles/<id>/``. A removed profile is kept (moved aside, not deleted) for
``PURGE_AFTER`` and can be restored until then.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from locuvi.config import Settings
from locuvi.errors import DomainError

PURGE_AFTER = timedelta(days=30)
NAME_RE = re.compile(r"[^\x00-\x1f]{1,40}")
MIN_PASSWORD = 10

log = logging.getLogger(__name__)
_lock = threading.RLock()  # restore/purge hold it across their check-and-change
_cache: dict[Path, list[Profile]] = {}  # this process is the only writer


@dataclass(frozen=True)
class Profile:
    id: int
    name: str
    password_hash: str | None
    is_admin: bool
    session_epoch: int
    created_at: str
    deleted_at: str | None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "is_admin": self.is_admin,
                "password_set": bool(self.password_hash),
                "created_at": self.created_at, "deleted_at": self.deleted_at}  # fmt: skip


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def registry_path(settings: Settings) -> Path:
    return settings.data_dir / "profiles.db"


@contextmanager
def _connect(settings: Settings) -> Iterator[sqlite3.Connection]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(registry_path(settings), timeout=15, isolation_level=None)
    try:
        _setup(conn)
        yield conn
    finally:
        conn.close()


def _setup(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS profile ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL,"
        " password_hash TEXT,"
        " is_admin INTEGER NOT NULL DEFAULT 0,"
        " session_epoch INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL,"
        " deleted_at TEXT)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS profile_name ON profile (name COLLATE NOCASE)"
        " WHERE deleted_at IS NULL"
    )


def _load(settings: Settings) -> list[Profile]:
    path = registry_path(settings)
    with _lock:
        rows = _cache.get(path)
        if rows is None:
            with _connect(settings) as conn:
                found = conn.execute(f"SELECT {_COLS} FROM profile ORDER BY id").fetchall()
            rows = _cache[path] = [_row(r) for r in found]
    return rows


def _changed(settings: Settings) -> None:
    _cache.pop(registry_path(settings), None)


def _row(r: tuple[Any, ...]) -> Profile:
    return Profile(r[0], r[1], r[2], bool(r[3]), int(r[4] or 0), r[5], r[6])


_COLS = "id, name, password_hash, is_admin, session_epoch, created_at, deleted_at"


def all_profiles(settings: Settings, *, deleted: bool = False) -> list[Profile]:
    return [p for p in _load(settings) if (p.deleted_at is not None) == deleted]


def get(settings: Settings, profile_id: int) -> Profile | None:
    return next((p for p in _load(settings) if p.id == profile_id), None)


def active(settings: Settings, profile_id: int) -> Profile | None:
    p = get(settings, profile_id)
    return p if p is not None and p.deleted_at is None else None


def by_name(settings: Settings, name: str) -> Profile | None:
    key = " ".join((name or "").split()).casefold()
    return next((p for p in all_profiles(settings) if p.name.casefold() == key), None)


def data_dir(settings: Settings, profile_id: int) -> Path:
    """Profile 1 is the original installation; the others have their own folder."""
    if profile_id == 1:
        return settings.data_dir
    return settings.data_dir / "profiles" / str(profile_id)


def settings_for(settings: Settings, profile_id: int) -> Settings:
    """The same settings, pointed at this profile's data (and its own backup folder)."""
    if profile_id == 1:
        return settings
    backup = settings.backup_dir / f"profile-{profile_id}" if settings.backup_dir else None
    remote = f"{settings.backup_remote_path}/profile-{profile_id}".strip("/")
    return replace(
        settings,
        data_dir=data_dir(settings, profile_id),
        backup_dir=backup,
        backup_remote_path=remote,  # off-site copies never collide between profiles
    )


def ensure_first(
    settings: Settings, name: str, password_hash: str | None, session_epoch: int = 0
) -> Profile:
    """Create profile 1 (the admin) from the existing installation, once."""
    with _lock, _connect(settings) as conn:
        _cache.pop(registry_path(settings), None)
        r = conn.execute(f"SELECT {_COLS} FROM profile WHERE id = 1").fetchone()
        if r is None:
            conn.execute(
                "INSERT INTO profile (id, name, password_hash, is_admin, session_epoch,"
                " created_at) VALUES (1, ?, ?, 1, ?, ?)",
                (
                    _clean_name(name) if name.strip() else "Owner",
                    password_hash,
                    int(session_epoch or 0),
                    _now(),
                ),  # fmt: skip
            )
            r = conn.execute(f"SELECT {_COLS} FROM profile WHERE id = 1").fetchone()
    return _row(r)


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not NAME_RE.fullmatch(name):
        raise DomainError("profile.bad_name", "Enter a name of up to 40 characters.")
    return name


def check_password_strength(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise DomainError(
            "profile.weak_password", f"Use a password of at least {MIN_PASSWORD} characters."
        )


def create(settings: Settings, name: str, password_hash: str) -> Profile:
    name = _clean_name(name)
    with _lock, _connect(settings) as conn:
        _cache.pop(registry_path(settings), None)
        clash = conn.execute(
            "SELECT 1 FROM profile WHERE name = ? COLLATE NOCASE AND deleted_at IS NULL", (name,)
        ).fetchone()
        if clash:
            raise DomainError("profile.name_taken", "There is already a profile with that name.")
        cur = conn.execute(
            "INSERT INTO profile (name, password_hash, is_admin, session_epoch, created_at)"
            " VALUES (?, ?, 0, 0, ?)",
            (name, password_hash, _now()),
        )
        pid = int(cur.lastrowid or 0)
    folder = data_dir(settings, pid)
    if folder.exists():  # a leftover from a purged profile with the same id: never reuse data
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    p = get(settings, pid)
    assert p is not None
    return p


def rename(settings: Settings, profile_id: int, name: str) -> Profile:
    name = _clean_name(name)
    with _lock, _connect(settings) as conn:
        _cache.pop(registry_path(settings), None)
        clash = conn.execute(
            "SELECT 1 FROM profile WHERE name = ? COLLATE NOCASE AND deleted_at IS NULL"
            " AND id <> ?",
            (name, profile_id),
        ).fetchone()
        if clash:
            raise DomainError("profile.name_taken", "There is already a profile with that name.")
        conn.execute("UPDATE profile SET name = ? WHERE id = ?", (name, profile_id))
    p = get(settings, profile_id)
    assert p is not None
    return p


def set_password(settings: Settings, profile_id: int, password_hash: str) -> Profile:
    """New password; every existing session of that profile is signed out."""
    with _lock, _connect(settings) as conn:
        _cache.pop(registry_path(settings), None)
        conn.execute(
            "UPDATE profile SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
            (password_hash, profile_id),
        )
    p = get(settings, profile_id)
    assert p is not None
    return p


def remove(settings: Settings, profile_id: int) -> Profile:
    """Remove a profile: signed out at once, data kept aside for PURGE_AFTER (restorable)."""
    p = active(settings, profile_id)
    if p is None:
        raise DomainError("profile.not_found", "That profile no longer exists.")
    if p.is_admin:
        raise DomainError("profile.admin", "The admin profile can't be removed.")
    with _lock, _connect(settings) as conn:
        _cache.pop(registry_path(settings), None)
        conn.execute(
            "UPDATE profile SET deleted_at = ?, session_epoch = session_epoch + 1 WHERE id = ?",
            (_now(), profile_id),
        )
    p2 = get(settings, profile_id)
    assert p2 is not None
    return p2


def restore(settings: Settings, profile_id: int) -> Profile:
    with _lock:  # serialised with purge_removed: a profile is either restored or purged
        _cache.pop(registry_path(settings), None)
        p = get(settings, profile_id)
        if p is None or p.deleted_at is None:
            raise DomainError("profile.not_found", "That profile can't be restored.")
        if by_name(settings, p.name) is not None:
            raise DomainError("profile.name_taken", "There is already a profile with that name.")
        with _connect(settings) as conn:
            conn.execute("UPDATE profile SET deleted_at = NULL WHERE id = ?", (profile_id,))
        _cache.pop(registry_path(settings), None)
        p2 = get(settings, profile_id)
    assert p2 is not None
    return p2


def purge_removed(settings: Settings, now: datetime | None = None) -> list[int]:
    """Delete the data of profiles removed more than PURGE_AFTER ago. A profile whose files
    can't be deleted keeps its entry, so the next run tries again."""
    cutoff = ((now or datetime.now(UTC)) - PURGE_AFTER).strftime("%Y-%m-%dT%H:%M:%SZ")
    purged: list[int] = []
    for candidate in all_profiles(settings, deleted=True):
        with _lock:
            _cache.pop(registry_path(settings), None)
            p = get(settings, candidate.id)  # re-check: it may have been restored meanwhile
            if p is None or p.deleted_at is None or p.deleted_at >= cutoff or p.id == 1:
                continue
            try:
                for folder in (data_dir(settings, p.id),
                               settings.backup_dir / f"profile-{p.id}" if settings.backup_dir
                               else None):  # fmt: skip
                    if folder is not None and folder.exists():
                        shutil.rmtree(folder)
            except OSError:
                log.exception("removed profile %s not purged yet; will retry", p.id)
                continue
            with _connect(settings) as conn:
                conn.execute("DELETE FROM profile WHERE id = ?", (p.id,))
            _cache.pop(registry_path(settings), None)
            purged.append(p.id)
    return purged


def find(settings: Settings, match: Any) -> int | None:
    """The first active profile whose database satisfies ``match(session)`` (used for links
    and tokens that arrive without a sign-in: calendar feeds, Bevro)."""
    from locuvi import db

    for p in all_profiles(settings) or [None]:
        pid = p.id if p else 1
        try:
            with db.use_profile(pid), db.new_session() as s:
                if match(s):
                    return pid
        except RuntimeError:  # that profile's database isn't open
            continue
    return None


def backup_registry(settings: Settings) -> Path | None:
    """Copy the profile list into the backup folder (overwritten each night), so a server
    rebuilt from backups knows its profiles again. It holds names and password hashes only."""
    if not settings.backup_dir or not registry_path(settings).is_file():
        return None
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.backup_dir / "profiles.db"
    tmp = dest.with_suffix(".db.partial")
    with _lock:
        src = sqlite3.connect(registry_path(settings))
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
    tmp.chmod(0o600)
    tmp.replace(dest)
    return dest
