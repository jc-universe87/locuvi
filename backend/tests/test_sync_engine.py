"""Two devices syncing through one folder (locuvi.sync.engine). Fictional data only."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.migrate import upgrade
from locuvi.models import AuthConfig, EmailConfig, MailboxConfig, Practice, WorkSession
from locuvi.secrets_store import SecretBox
from locuvi.services import core
from locuvi.sync import engine
from locuvi.sync.targets import FolderTarget


class Device:
    def __init__(self, root: Path, name: str) -> None:
        self.settings = Settings(
            app_env="test",
            data_dir=root / name / "data",
            key_dir=root / name / "keys",
            auth_mode="gateway",
            cookie_secure=False,
            worker_enabled=False,
        )
        self.name = name
        self.secrets = SecretBox(self.settings)
        eng = db.make_engine(self.settings.db_path)
        upgrade(eng)
        self.engine = eng
        with self.session() as s:
            core.ensure_singletons(s)
            s.commit()

    def session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def file(self, rel: str, data: bytes) -> None:
        f = self.settings.data_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)

    def sync(self, **kw) -> engine.Report:
        return engine.sync_now(self.settings, self.secrets, **kw)


@pytest.fixture
def cloud(tmp_path: Path) -> Path:
    d = tmp_path / "Google Drive"  # stands for any folder a cloud app keeps in step
    d.mkdir()
    return d


@pytest.fixture
def pair(tmp_path: Path, cloud: Path):
    a, b = Device(tmp_path, "laptop"), Device(tmp_path, "phone")
    with a.session() as s:
        core.get_profile(s).legal_name = "Dr Alex Example"
        s.add(Practice(id="p1", name="Example Surgery"))
        email = s.get(EmailConfig, 1) or EmailConfig(id=1)
        email.host = "smtp.example.invalid"
        email.password_ciphertext = a.secrets.encrypt("app-password-1")
        s.add(email)
        s.add(MailboxConfig(id=1, label="Locum mail", host="imap.example.invalid",
                            username="alex@example.invalid",
                            password_ciphertext=a.secrets.encrypt("mailbox-pw")))  # fmt: skip
        s.commit()
    a.file("invoices/issued/inv-1.pdf", b"%PDF-1.7 fictional invoice")
    spec = {"kind": "folder", "path": str(cloud)}
    code = engine.start(a.settings, a.secrets, spec, "Laptop")
    with b.session() as s:  # the phone had a saved secret of its own before joining
        s.add(MailboxConfig(id=1, label="Phone mail", host="imap.example.invalid",
                            username="alex@example.invalid",
                            password_ciphertext=b.secrets.encrypt("phone-pw")))  # fmt: skip
        s.commit()
    engine.join(b.settings, b.secrets, spec, "Phone", code.lower().replace("-", " "))
    return a, b, code, spec


def test_joining_brings_records_files_and_saved_passwords(pair):
    a, b, _code, _spec = pair
    with b.session() as s:
        assert core.get_profile(s).legal_name == "Dr Alex Example"
        assert s.get(Practice, "p1").name == "Example Surgery"
        cfg = s.get(EmailConfig, 1)
        assert b.secrets.decrypt(cfg.password_ciphertext) == "app-password-1"
        # its own mailbox stays its own, and still opens with the shared key
        mb = s.get(MailboxConfig, 1)
        assert mb.label == "Phone mail" and b.secrets.decrypt(mb.password_ciphertext) == "phone-pw"
    assert (b.settings.data_dir / "invoices/issued/inv-1.pdf").read_bytes().startswith(b"%PDF")


def test_changes_travel_both_ways(pair):
    a, b, _code, _spec = pair
    with b.session() as s:
        s.add(WorkSession(id="w1", practice_id="p1", date=date(2026, 9, 1), unit="am",
                          rate=Decimal("300.00")))  # fmt: skip
        s.commit()
    b.file("documents/booking.txt", b"Locum booking, Example Surgery")
    with a.session() as s:
        s.add(Practice(id="p2", name="Example Health Centre"))
        s.commit()
    b.sync()
    a.sync()
    b.sync()
    for dev in (a, b):
        with dev.session() as s:
            assert s.get(WorkSession, "w1") is not None
            assert s.get(Practice, "p2") is not None
        assert (dev.settings.data_dir / "documents/booking.txt").is_file()


def test_nothing_private_to_a_device_reaches_the_folder(pair, cloud):
    a, _b, code, _spec = pair
    with a.session() as s:
        auth = s.get(AuthConfig, 1) or AuthConfig(id=1)
        auth.password_hash = "fictional-hash"
        s.add(auth)
        s.commit()
    a.sync()
    data, _v = FolderTarget(cloud).read_state()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        remote = engine._open_state(data, code, Path(tmp))
        c = sqlite3.connect(remote.db_path)
        assert c.execute("SELECT count(*) FROM mailbox_config").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM auth_config").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM practice").fetchone()[0] == 1
        c.close()
    blobs = (cloud / "Locuvi Sync" / "blobs").iterdir()
    assert all(b"fictional invoice" not in p.read_bytes() for p in blobs)  # encrypted


def test_wrong_code_changes_nothing(tmp_path, pair):
    _a, _b, _code, spec = pair
    c = Device(tmp_path, "tablet")
    with pytest.raises(DomainError) as e:
        engine.join(c.settings, c.secrets, spec, "Tablet", "AAAA-BBBB-CCCC-DDDD-EEEE")
    assert e.value.code == "sync.wrong_code"
    assert not engine.load_config(c.settings).enabled
    with c.session() as s:
        assert s.get(Practice, "p1") is None


def test_start_and_join_check_the_folder(tmp_path, pair, cloud):
    _a, _b, code, spec = pair
    c = Device(tmp_path, "tablet")
    with pytest.raises(DomainError) as e:
        engine.start(c.settings, c.secrets, spec, "Tablet")
    assert e.value.code == "sync.already_started"
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DomainError) as e:
        engine.join(c.settings, c.secrets, {"kind": "folder", "path": str(empty)}, "T", code)
    assert e.value.code == "sync.nothing_there"


def test_numbering_lease_keeps_devices_apart(pair):
    a, b, _code, _spec = pair
    a.sync(lease=True)
    with pytest.raises(DomainError) as e:
        b.sync(lease=True)
    assert e.value.code == "sync.busy"
    b.sync()  # an ordinary sync still works meanwhile
    a.sync(release=True)
    b.sync(lease=True)


def test_a_device_that_synced_meanwhile_is_merged_not_overwritten(pair, cloud, monkeypatch):
    a, b, _code, _spec = pair
    with a.session() as s:
        s.add(Practice(id="pa", name="Added on the laptop"))
        s.commit()
    with b.session() as s:
        s.add(Practice(id="pb", name="Added on the phone"))
        s.commit()
    real = FolderTarget.write_state
    raced = {"done": False}

    def write_after_phone(self, data, version):
        if not raced["done"]:
            raced["done"] = True
            b.sync()  # the phone gets in first
        return real(self, data, version)

    monkeypatch.setattr(FolderTarget, "write_state", write_after_phone)
    a.sync()
    monkeypatch.setattr(FolderTarget, "write_state", real)
    b.sync()
    for dev in (a, b):
        with dev.session() as s:
            assert {"pa", "pb"} <= {p.id for p in s.query(Practice)}


def test_newer_locuvi_elsewhere_asks_for_an_update(pair, cloud):
    a, b, code, _spec = pair
    a.sync()
    import tempfile

    target = FolderTarget(cloud)
    data, version = target.read_state()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        remote = engine._open_state(data, code, work)
        c = sqlite3.connect(remote.db_path)
        c.execute("UPDATE alembic_version SET version_num = '9999_from_the_future'")
        c.commit()
        c.close()
        sealed = engine._seal_state(work, remote.db_path, remote.files, remote.meta, code)
    assert target.write_state(sealed, version)
    with pytest.raises(DomainError) as e:
        b.sync()
    assert e.value.code == "sync.update_needed"
    assert engine.load_config(b.settings).last_error["code"] == "sync.update_needed"


def test_export_and_import_everything(tmp_path, pair):
    a, _b, _code, _spec = pair
    blob = engine.export_everything(a.settings, "a long export passphrase")
    assert b"Example Surgery" not in blob
    fresh = Device(tmp_path, "new-laptop")
    with pytest.raises(DomainError):
        engine.import_everything(fresh.settings, blob, "the wrong passphrase!")
    n = engine.import_everything(fresh.settings, blob, "a long export passphrase")
    assert n > 0
    with fresh.session() as s:
        assert s.get(Practice, "p1").name == "Example Surgery"
        assert s.get(MailboxConfig, 1) is None  # device-only settings aren't exported
    assert (fresh.settings.data_dir / "invoices/issued/inv-1.pdf").is_file()


def test_code_format(tmp_path):
    code = engine.new_code()
    assert len(code) == 24 and code.count("-") == 4
    assert engine.normalise_code(code.lower().replace("-", "")) == code
    with pytest.raises(DomainError):
        engine.normalise_code("short")


def test_profile_settings_are_separate(tmp_path):
    s = Settings(data_dir=tmp_path / "d", key_dir=tmp_path / "k")
    other = replace(s, data_dir=tmp_path / "d" / "profiles" / "2")
    assert engine.sync_dir(s) != engine.sync_dir(other)
