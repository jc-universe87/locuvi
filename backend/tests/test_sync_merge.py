"""Three-way merge of two devices' records (locuvi.sync.merge). Fictional data only."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from locuvi import db
from locuvi.migrate import upgrade
from locuvi.models import Base, Invoice, InvoiceSequence, OwnerProfile, Practice, WorkSession
from locuvi.services import core
from locuvi.sync import merge as m


def _fresh(path: Path) -> None:
    from sqlalchemy.orm import Session

    eng = db.make_engine(path)
    upgrade(eng)
    with Session(eng) as s:
        core.ensure_singletons(s)
        s.commit()
    eng.dispose()


@pytest.fixture
def trio(tmp_path: Path):
    """A shared start (base), then two devices that each carry on from it."""
    base = tmp_path / "base.db"
    _fresh(base)
    with _session(base) as s:
        p = core.get_profile(s)
        p.legal_name = "Dr Alex Example"
        s.add(Practice(id="p1", name="Example Surgery", billing_email="accounts@example.invalid"))
        s.commit()
    local, remote = tmp_path / "local.db", tmp_path / "remote.db"
    _settle(base)
    shutil.copy(base, local)
    shutil.copy(base, remote)
    return base, local, remote


def _settle(path: Path) -> None:
    """Fold the write-ahead log into the file, so a plain file copy has everything."""
    c = sqlite3.connect(path)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()


def _same_start(base: Path, *others: Path) -> None:
    _settle(base)
    for o in others:
        for suffix in ("-wal", "-shm"):
            Path(str(o) + suffix).unlink(missing_ok=True)
        shutil.copy(base, o)


def _session(path: Path):
    from sqlalchemy.orm import Session

    return Session(db.make_engine(path), expire_on_commit=False)


def _merge(base: Path | None, local: Path, remote: Path) -> m.MergeResult:
    lc = sqlite3.connect(local, isolation_level=None)
    bc = sqlite3.connect(base) if base else None
    rc = sqlite3.connect(remote)
    try:
        return m.merge(lc, bc, rc)
    finally:
        lc.close()
        rc.close()
        if bc:
            bc.close()


def test_every_table_is_synced_or_deliberately_local():
    """A new table must be put on one side on purpose (see LOCAL_TABLES)."""
    names = {t.name for t in Base.metadata.sorted_tables}
    synced = {t.name for t in m.synced_tables()}
    assert synced | (m.LOCAL_TABLES & names) == names
    assert {"invoice", "invoice_line", "work_session", "practice", "document"} <= synced
    assert "mailbox_config" not in synced and "auth_config" not in synced


def test_changes_on_each_side_are_combined(trio):
    base, local, remote = trio
    with _session(local) as s:
        s.add(WorkSession(id="w-local", practice_id="p1", date=date(2026, 9, 1), unit="am",
                          rate=Decimal("300.00")))  # fmt: skip
        s.get(Practice, "p1").contact_name = "Sam Example"
        s.commit()
    with _session(remote) as s:
        s.add(WorkSession(id="w-remote", practice_id="p1", date=date(2026, 9, 2), unit="pm",
                          rate=Decimal("300.00")))  # fmt: skip
        s.get(Practice, "p1").billing_address = "1 Example Road, SF1 1AA"
        s.commit()
    r = _merge(base, local, remote)
    assert r.remote_needs_update
    with _session(local) as s:
        assert {w.id for w in s.query(WorkSession)} == {"w-local", "w-remote"}
        p = s.get(Practice, "p1")
        assert p.contact_name == "Sam Example" and p.billing_address == "1 Example Road, SF1 1AA"


def test_deletion_on_one_side_spreads_but_an_edit_wins_over_a_delete(trio):
    base, local, remote = trio
    with _session(base) as s:
        for i in (1, 2):
            s.add(WorkSession(id=f"w{i}", practice_id="p1", date=date(2026, 9, i), unit="am",
                              rate=Decimal("300.00")))  # fmt: skip
        s.commit()
    _same_start(base, local, remote)
    with _session(remote) as s:
        s.delete(s.get(WorkSession, "w1"))  # deleted there, untouched here: goes
        s.delete(s.get(WorkSession, "w2"))  # deleted there, edited here: stays
        s.commit()
    with _session(local) as s:
        s.get(WorkSession, "w2").rate = Decimal("320.00")
        s.commit()
    _merge(base, local, remote)
    with _session(local) as s:
        assert s.get(WorkSession, "w1") is None
        assert s.get(WorkSession, "w2").rate == Decimal("320.00")


def test_same_field_changed_twice_newest_wins(trio):
    base, local, remote = trio
    with _session(remote) as s:
        s.get(Practice, "p1").name = "Example Surgery (old name)"
        s.commit()
    with _session(local) as s:
        s.get(Practice, "p1").name = "Example Health Centre"
        s.commit()  # later, so newer
    _merge(base, local, remote)
    with _session(local) as s:
        assert s.get(Practice, "p1").name == "Example Health Centre"


def test_joining_device_never_overwrites_the_sync_folder(tmp_path):
    """No base yet: a new phone's empty profile must not wipe the real one."""
    remote, local = tmp_path / "remote.db", tmp_path / "phone.db"
    _fresh(remote)
    _fresh(local)
    with _session(remote) as s:
        core.get_profile(s).legal_name = "Dr Alex Example"
        s.add(Practice(id="p1", name="Example Surgery"))
        s.commit()
    with _session(local) as s:
        s.get(OwnerProfile, 1).trading_name = "Phone Locum"  # changed later, still loses
        s.add(Practice(id="p-phone", name="Practice added on the phone"))
        s.commit()
    _merge(None, local, remote)
    with _session(local) as s:
        assert core.get_profile(s).legal_name == "Dr Alex Example"
        assert {p.id for p in s.query(Practice)} == {"p1", "p-phone"}


def _issued(s, inv_id: str, number: str) -> None:
    inv = s.get(Invoice, inv_id)
    inv.status = "issued"
    inv.invoice_number = number
    s.commit()


def test_issued_invoice_never_goes_back_to_draft(trio):
    base, local, remote = trio
    with _session(base) as s:
        s.add(Invoice(id="i1", practice_id="p1", status="draft"))
        s.commit()
    _same_start(base, local, remote)
    with _session(remote) as s:
        _issued(s, "i1", "LOC-2026-0001")
    with _session(local) as s:
        s.get(Invoice, "i1").reference = "edited on an offline phone after it was issued"
        s.commit()
    _merge(base, local, remote)
    with _session(local) as s:
        inv = s.get(Invoice, "i1")
        assert inv.status == "issued" and inv.invoice_number == "LOC-2026-0001"
        assert inv.reference != "edited on an offline phone after it was issued"


def test_numbering_only_moves_forward(trio):
    base, local, remote = trio
    with _session(remote) as s:
        s.get(InvoiceSequence, 1).next_number = 7
        s.commit()
    with _session(local) as s:
        s.get(InvoiceSequence, 1).next_number = 5
        s.commit()
    _merge(base, local, remote)
    with _session(local) as s:
        assert s.get(InvoiceSequence, 1).next_number == 7


def test_two_issued_invoices_with_one_number_stop_the_sync(trio):
    base, local, remote = trio
    with _session(local) as s:
        s.add(Invoice(id="a", practice_id="p1", status="draft"))
        s.commit()
        _issued(s, "a", "LOC-2026-0003")
    with _session(remote) as s:
        s.add(Invoice(id="b", practice_id="p1", status="draft"))
        s.commit()
        _issued(s, "b", "LOC-2026-0003")
    before = local.read_bytes()
    with pytest.raises(m.SyncConflict) as e:
        _merge(base, local, remote)
    assert e.value.code == "sync.duplicate_number"
    with _session(local) as s:  # nothing half-applied
        assert {i.id for i in s.query(Invoice)} == {"a"}
    assert local.read_bytes()[:16] == before[:16]


def test_merging_twice_changes_nothing(trio):
    base, local, remote = trio
    with _session(remote) as s:
        s.add(WorkSession(id="w9", practice_id="p1", date=date(2026, 9, 9), unit="day",
                          rate=Decimal("600.00")))  # fmt: skip
        s.commit()
    assert _merge(base, local, remote).total == 1
    again = _merge(base, local, remote)
    assert again.total == 0 and not again.remote_needs_update
