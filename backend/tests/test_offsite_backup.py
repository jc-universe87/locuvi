"""Encrypted off-server backups and the restore drill. Disposable WebDAV only; fictional data."""

import uuid
from dataclasses import replace

import pytest
from conftest import line
from webdav_fixture import PASSWORD, USER, DavServer

from locuvi import backup_crypto, cli, db
from locuvi.config import WebDavAllowlist
from locuvi.secrets_store import SecretBox
from locuvi.services import backups, checks
from locuvi.services import invoices as svc
from locuvi.storage.local import sha256_file
from locuvi.webdav import archive

PASS = "correct horse battery staple"


@pytest.fixture
def dav(tmp_path):
    srv = DavServer(tmp_path / "davroot")
    yield srv
    srv.stop()


@pytest.fixture
def st(settings, tmp_path):
    return replace(
        settings,
        backup_dir=tmp_path / "backups",
        backup_passphrase=PASS,
        webdav_allowlist=WebDavAllowlist.parse("127.0.0.1"),
        webdav_allow_http_for_allowlisted=True,
        webdav_timeout_seconds=5,
    )


def issue_one(st, session, ready):
    inv = svc.save_draft(session, None, practice_id=ready.id, lines=[line("2026-10-08")])
    return svc.issue(st, inv.id, uuid.uuid4().hex).invoice


def connect(st, dav):
    archive.save_config(
        db.new_session(), archive.ArchiveContext(st, SecretBox(st)), enabled=True,
        target_url=dav.base_url, username=USER, base_path="Locuvi/Invoices",
        auto_upload=False, password=PASSWORD,
    )  # fmt: skip


def kinds(session, st):
    session.commit()
    return {f.kind for f in checks.run_checks(session, st)}


# ------------------------------------------------------------------ encryption


def test_encryption_roundtrip_and_tamper_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_crypto, "CHUNK", 1000)  # several chunks
    src = tmp_path / "plain.bin"
    src.write_bytes(bytes(range(256)) * 20)
    enc, out = tmp_path / "x.enc", tmp_path / "out.bin"
    backup_crypto.encrypt_file(src, enc, PASS)
    assert src.read_bytes() not in enc.read_bytes() and enc.stat().st_mode & 0o077 == 0
    backup_crypto.decrypt_file(enc, out, PASS)
    assert out.read_bytes() == src.read_bytes()

    out.unlink()
    with pytest.raises(backup_crypto.DecryptError):
        backup_crypto.decrypt_file(enc, out, "wrong passphrase!!")
    raw = enc.read_bytes()
    for damaged in (
        raw[:-1],  # truncated tag
        raw[: backup_crypto.HEADER_LEN + 4 + 1016],  # whole final chunks cut off
        raw[:200] + bytes([raw[200] ^ 1]) + raw[201:],  # one flipped bit
        b"not a backup" + raw,
    ):
        enc.write_bytes(damaged)
        with pytest.raises(backup_crypto.DecryptError):
            backup_crypto.decrypt_file(enc, out, PASS)
        assert not out.exists() and not list(tmp_path.glob("*.partial"))
    with pytest.raises(ValueError):
        backup_crypto.encrypt_file(src, enc, "short")


# ------------------------------------------------------------- off-server copy


def test_encrypted_copy_uploaded_verified_and_drilled(st, session, ready, dav, tmp_path):
    inv = issue_one(st, session, ready)
    assert "backup_offsite_off" not in kinds(session, st)  # passphrase is set
    connect(st, dav)
    res = backups.backup_now(st)
    assert res["offsite"] == "synced" and res["drill_ok"] is True
    enc = st.backup_dir / (res["file"] + ".enc")
    remote = dav.root / "Locuvi" / "Backups" / enc.name
    assert remote.read_bytes() == enc.read_bytes()
    assert b"Example Medical Practice" not in remote.read_bytes()  # nothing readable leaves

    drill = backups.read_marker(st, backups.DRILL_MARKER)
    assert drill["ok"] and drill["encrypted"] and drill["issued_invoices"] == 1
    assert not {"restore_drill_failed", "backup_offsite_failed", "backup_offsite_off"} & kinds(
        session, st
    )

    # the off-server copy alone restores everything
    db.get_engine().dispose()
    target = replace(st, data_dir=tmp_path / "restored")
    cli.restore(target, remote)
    assert sha256_file(target.data_dir / inv.local_pdf_path) == inv.local_pdf_sha256
    assert cli.verify(target)["ok"] is True
    with pytest.raises(SystemExit, match="encrypted"):
        cli.restore(replace(target, backup_passphrase=None), remote, force=True)


def test_remote_never_overwritten_and_failures_reported(st, session, ready, dav):
    issue_one(st, session, ready)
    res = backups.backup_now(st)  # passphrase but no Nextcloud: encrypted local copy only
    assert res["offsite"] == "local_only" and res["drill_ok"]
    assert "backup_offsite_off" in kinds(session, st)

    connect(st, dav)
    plain = st.backup_dir / "locuvi-2026-10-09-020000.tar.gz"
    cli.backup(st, plain)
    taken = dav.root / "Locuvi" / "Backups" / (plain.name + ".enc")
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"someone else's file")
    out = backups.offsite_copy(st, plain)
    assert out == out | {"status": "failed", "error": "conflict"}
    assert taken.read_bytes() == b"someone else's file"
    assert "backup_offsite_failed" in kinds(session, st)
    assert PASS not in (st.data_dir / backups.OFFSITE_MARKER).read_text()


def test_restore_drill_catches_a_damaged_backup(st, session, ready, monkeypatch):
    issue_one(st, session, ready)
    res = backups.backup_now(st)
    assert res["drill_ok"]
    enc = st.backup_dir / (res["file"] + ".enc")
    data = bytearray(enc.read_bytes())
    data[-40] ^= 0xFF
    enc.write_bytes(bytes(data))
    result = backups.restore_drill(st)
    assert not result["ok"] and "decrypt" in result["error"]
    found = [f for f in checks.run_checks(db.new_session(), st)
             if f.kind == "restore_drill_failed"]  # fmt: skip
    assert found and found[0].severity == "urgent" and not found[0].dismissible

    # CLI: drill a named file with the passphrase from a file; decrypt the good copy
    pf = st.data_dir / "pass.txt"
    pf.write_text(PASS)
    monkeypatch.setenv("DATA_DIR", str(st.data_dir))
    assert cli.main(["drill", str(enc), "--passphrase-file", str(pf)]) == 1
    good = st.backup_dir / res["file"]
    assert backups.restore_drill(st, good)["ok"] is True


def test_no_passphrase_means_local_only_finding(settings, session, ready, tmp_path):
    st = replace(settings, backup_dir=tmp_path / "b")
    issue_one(st, session, ready)
    res = backups.backup_now(st)
    assert res["offsite"] == "off" and res["drill_ok"]
    assert not list(st.backup_dir.glob("*.enc"))
    assert "backup_offsite_off" in kinds(session, st)
    assert "correct horse" not in repr(replace(st, backup_passphrase=PASS))
