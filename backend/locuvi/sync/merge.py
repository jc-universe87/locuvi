"""Three-way merge of two Locuvi databases, row by row.

``base`` is the copy both sides last agreed on (from the previous sync), ``local`` is this
device and ``remote`` is the copy in the sync folder. For each row:

- changed on one side only: that side's version is taken (including deletions);
- changed on both sides: column by column. A column changed on one side takes that change;
  a column both changed takes the newer row's value (``updated_at``), else the remote's;
- deleted on one side, edited on the other: the edit is kept (nothing is lost silently);
- no base yet (this device is joining): the remote wins any clash, so a new phone's empty
  settings never overwrite the records already in the sync folder.

Rules that must never regress, applied on top:

- an issued invoice never goes back to a draft (draft < issued < voided), and its lines are
  exactly the ones of the side that issued it;
- numbering (``invoice_sequence``) only moves forward: the larger next number wins;
- a natural key (an invoice number, a bank line's fingerprint, a month's Form B) that ends up
  on two different rows is the same thing recorded twice: the older row is kept, references to
  the other are moved to it. Two *issued* invoices with one number can't be fixed that way and
  stop the sync instead (``SyncConflict``).

Only stdlib ``sqlite3`` is used, so this also runs in the phone app (Pyodide).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Table

from locuvi.models import Base

# Kept on each device only, never synced:
#   mail accounts and their progress: only the computer that reads email has them (two
#     computers reading the same mailbox would file every email twice);
#   archive jobs: each device copies its own PDFs to Nextcloud;
#   the calendar feed and agent tokens: links served by this device;
#   the sign-in password.
LOCAL_TABLES = frozenset(
    {
        "alembic_version",
        "mailbox_config",
        "mail_folder_progress",
        "archive_job",
        "calendar_feed",
        "agent_token",
        "auth_config",
    }
)

STATUS_RANK = {"draft": 0, "issued": 1, "voided": 2}

Row = tuple[Any, ...]
Key = tuple[Any, ...]


class SyncConflict(Exception):
    """The two copies disagree in a way Locuvi must not decide alone."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


@dataclass
class TableInfo:
    name: str
    columns: list[str]
    pk: list[str]
    uniques: list[list[str]]
    # (column here, referenced table, referenced column)
    fks: list[tuple[str, str, str]] = field(default_factory=list)


def synced_tables() -> list[TableInfo]:
    """Tables in dependency order (parents first)."""
    out = []
    for t in Base.metadata.sorted_tables:
        if t.name in LOCAL_TABLES:
            continue
        out.append(_info(t))
    return out


def _info(t: Table) -> TableInfo:
    uniques: list[list[str]] = []
    for c in t.columns:
        if c.unique:
            uniques.append([c.name])
    for con in t.constraints:
        cols = [c.name for c in getattr(con, "columns", [])]
        if con.__class__.__name__ == "UniqueConstraint" and cols and cols not in uniques:
            uniques.append(cols)
    fks = [
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in t.foreign_keys
        if fk.column.table.name not in LOCAL_TABLES
    ]
    return TableInfo(
        name=t.name,
        columns=[c.name for c in t.columns],
        pk=[c.name for c in t.primary_key.columns],
        uniques=uniques,
        fks=fks,
    )


def _rows(conn: sqlite3.Connection | None, t: TableInfo) -> dict[Key, Row]:
    if conn is None:
        return {}
    have = {r[1] for r in conn.execute(f'PRAGMA table_info("{t.name}")')}
    if not have:
        return {}
    cols = ", ".join(f'"{c}"' if c in have else "NULL" for c in t.columns)
    idx = [t.columns.index(p) for p in t.pk]
    out = {}
    for row in conn.execute(f'SELECT {cols} FROM "{t.name}"'):
        out[tuple(row[i] for i in idx)] = tuple(row)
    return out


@dataclass
class MergeResult:
    changed: dict[str, int] = field(default_factory=dict)  # table -> rows written locally
    remote_needs_update: bool = False  # local had something the remote doesn't

    @property
    def total(self) -> int:
        return sum(self.changed.values())


def _newer(t: TableInfo, a: Row, b: Row) -> bool:
    """True when row ``a`` was changed later than row ``b`` (by updated_at)."""
    if "updated_at" not in t.columns:
        return False
    i = t.columns.index("updated_at")
    return (a[i] or "") > (b[i] or "")


def _merge_row(t: TableInfo, b: Row | None, local: Row | None, remote: Row | None) -> Row | None:
    if local == remote:
        return local
    if b is None:
        if local is None:
            return remote
        if remote is None:
            return local
        return remote  # both created the same row without a common base: the sync folder wins
    if local == b:
        return remote
    if remote == b:
        return local
    if local is None:
        return remote  # deleted here, edited there: keep the edit
    if remote is None:
        return local
    local_newer = _newer(t, local, remote)
    merged = []
    for i in range(len(t.columns)):
        if local[i] == b[i]:
            merged.append(remote[i])
        elif remote[i] == b[i]:
            merged.append(local[i])
        else:
            merged.append(local[i] if local_newer else remote[i])
    return tuple(merged)


def _col(t: TableInfo, row: Row, name: str) -> Any:
    return row[t.columns.index(name)]


def _invoice_rules(
    t: TableInfo, local: dict[Key, Row], remote: dict[Key, Row], out: dict[Key, Row | None]
) -> dict[Key, str]:
    """Issued invoices never go backwards. Returns {invoice key: 'local'|'remote'} for every
    invoice whose lines must come from one side (the side that issued it)."""
    owner: dict[Key, str] = {}
    for key in set(local) | set(remote):
        lo, re_ = local.get(key), remote.get(key)
        if lo is None or re_ is None:
            continue
        rl = STATUS_RANK.get(_col(t, lo, "status"), 0)
        rr = STATUS_RANK.get(_col(t, re_, "status"), 0)
        if rl == rr == 0:
            continue
        if rl != rr:
            # the further-along side wins outright: a draft edit made elsewhere can't undo an
            # issue or a void, and an issued invoice keeps its own number, snapshot and PDF
            out[key] = lo if rl > rr else re_
            if min(rl, rr) == 0:
                owner[key] = "local" if rl > rr else "remote"
            continue
        # both issued (or both voided): number, snapshot and PDF can't differ, unless two
        # devices each issued it, which can't happen to the same invoice id
        for col in ("invoice_number", "local_pdf_sha256"):
            if col in t.columns and _col(t, lo, col) != _col(t, re_, col):
                raise SyncConflict(
                    "sync.invoice_differs",
                    "An issued invoice is different on two devices.",
                    invoice=_col(t, lo, "invoice_number") or _col(t, re_, "invoice_number"),
                )
    return owner


def merge(
    local: sqlite3.Connection,
    base: sqlite3.Connection | None,
    remote: sqlite3.Connection,
) -> MergeResult:
    """Bring ``local`` to the merged state, in one transaction. ``base``/``remote`` are read only.

    The caller opens ``local`` with isolation_level=None; foreign keys are checked at the end
    and any problem rolls everything back.
    """
    tables = synced_tables()
    result = MergeResult()
    plan: dict[str, tuple[TableInfo, dict[Key, Row], dict[Key, Row | None]]] = {}
    remote_rows: dict[str, dict[Key, Row]] = {}

    local.execute("PRAGMA foreign_keys=OFF")
    local.execute("BEGIN IMMEDIATE")
    try:
        line_owner: dict[Key, str] = {}
        for t in tables:
            lo, ba, re_ = _rows(local, t), _rows(base, t), _rows(remote, t)
            remote_rows[t.name] = re_
            out: dict[Key, Row | None] = {}
            for key in set(lo) | set(ba) | set(re_):
                out[key] = _merge_row(t, ba.get(key), lo.get(key), re_.get(key))
            if t.name == "invoice":
                line_owner = _invoice_rules(t, lo, re_, out)
            elif t.name in ("invoice_line",) and line_owner:
                _lines_follow_issuer(t, lo, re_, out, line_owner)
            elif t.name == "invoice_sequence":
                _sequence_forward(t, lo, re_, out)
            plan[t.name] = (t, lo, out)

        _dedupe_natural_keys(plan)

        for t, lo, out in plan.values():
            n = _write(local, t, lo, out)
            if n:
                result.changed[t.name] = n
            re_ = remote_rows[t.name]
            if any(re_.get(k) != v for k, v in out.items() if v is not None) or any(
                v is None and k in re_ for k, v in out.items()
            ):
                result.remote_needs_update = True

        problems = local.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise SyncConflict(
                "sync.broken_links",
                "The merged records don't fit together.",
                table=problems[0][0],
            )
        local.execute("COMMIT")
    except BaseException:
        local.execute("ROLLBACK")
        raise
    finally:
        local.execute("PRAGMA foreign_keys=ON")
    return result


def _lines_follow_issuer(
    t: TableInfo,
    local: dict[Key, Row],
    remote: dict[Key, Row],
    out: dict[Key, Row | None],
    owner: dict[Key, str],
) -> None:
    for key in set(local) | set(remote):
        row = local.get(key) or remote.get(key)
        assert row is not None
        side = owner.get((_col(t, row, "invoice_id"),))
        if side is None:
            continue
        chosen = (local if side == "local" else remote).get(key)
        out[key] = chosen  # absent on the issuing side means it wasn't on the invoice


def _sequence_forward(
    t: TableInfo, local: dict[Key, Row], remote: dict[Key, Row], out: dict[Key, Row | None]
) -> None:
    for key, row in out.items():
        if row is None:
            continue
        merged = list(row)
        for col in ("next_number", "credit_next_number"):
            if col not in t.columns:
                continue
            i = t.columns.index(col)
            vals = [r[i] for r in (local.get(key), remote.get(key), row) if r is not None]
            merged[i] = max(v for v in vals if v is not None)
        out[key] = tuple(merged)


def _dedupe_natural_keys(
    plan: dict[str, tuple[TableInfo, dict[Key, Row], dict[Key, Row | None]]],
) -> None:
    for t, _lo, out in list(plan.values()):
        for cols in t.uniques:
            if set(cols) == set(t.pk):
                continue
            idx = [t.columns.index(c) for c in cols]
            seen: dict[Key, Key] = {}
            for key in sorted(k for k, v in out.items() if v is not None):
                row = out[key]
                assert row is not None
                nat = tuple(row[i] for i in idx)
                if any(v is None for v in nat):
                    continue
                if nat not in seen:
                    seen[nat] = key
                    continue
                keep, drop = _older(t, out, seen[nat], key)
                if (
                    t.name in ("invoice", "credit_note")
                    and _issued(t, out[keep])
                    and _issued(t, out[drop])
                ):
                    raise SyncConflict(
                        "sync.duplicate_number",
                        "Two devices issued different invoices with the same number.",
                        number=nat[0],
                    )
                seen[nat] = keep
                out[drop] = None
                _repoint(plan, t.name, drop, keep)


def _issued(t: TableInfo, row: Row | None) -> bool:
    if row is None:
        return False
    if "status" in t.columns:
        return STATUS_RANK.get(_col(t, row, "status"), 0) > 0
    return True  # a credit note exists only once it is issued


def _older(t: TableInfo, out: dict[Key, Row | None], a: Key, b: Key) -> tuple[Key, Key]:
    ra, rb = out[a], out[b]
    assert ra is not None and rb is not None
    if "created_at" in t.columns:
        ca, cb = _col(t, ra, "created_at") or "", _col(t, rb, "created_at") or ""
        if ca != cb:
            return (a, b) if ca < cb else (b, a)
    return (a, b) if a < b else (b, a)


def _repoint(
    plan: dict[str, tuple[TableInfo, dict[Key, Row], dict[Key, Row | None]]],
    table: str,
    old: Key,
    new: Key,
) -> None:
    if len(old) != 1:
        return
    for t, _lo, out in plan.values():
        for col, ref_table, _ref_col in t.fks:
            if ref_table != table:
                continue
            i = t.columns.index(col)
            for key, row in out.items():
                if row is not None and row[i] == old[0]:
                    r = list(row)
                    r[i] = new[0]
                    out[key] = tuple(r)


def _write(
    conn: sqlite3.Connection, t: TableInfo, local: dict[Key, Row], out: dict[Key, Row | None]
) -> int:
    have = [r[1] for r in conn.execute(f'PRAGMA table_info("{t.name}")')]
    cols = [c for c in t.columns if c in have]
    sel = [t.columns.index(c) for c in cols]
    where = " AND ".join(f'"{p}" = ?' for p in t.pk)
    n = 0
    for key, row in out.items():
        if local.get(key) == row:
            continue
        n += 1
        conn.execute(f'DELETE FROM "{t.name}" WHERE {where}', key)
        if row is not None:
            marks = ", ".join("?" for _ in cols)
            names = ", ".join(f'"{c}"' for c in cols)
            conn.execute(
                f'INSERT INTO "{t.name}" ({names}) VALUES ({marks})', [row[i] for i in sel]
            )
    return n


def table_names(tables: Iterable[TableInfo]) -> list[str]:
    return [t.name for t in tables]
