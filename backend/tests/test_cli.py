import uuid
from dataclasses import replace

import pytest
from conftest import line

from locuvi import cli, db
from locuvi.services import invoices as svc
from locuvi.storage.local import sha256_file


def test_backup_restore_roundtrip(settings, session, ready, tmp_path):
    inv = svc.save_draft(session, None, practice_id=ready.id, lines=[line("2026-10-08")])
    issued = svc.issue(settings, inv.id, uuid.uuid4().hex).invoice
    archive = tmp_path / "b" / "locuvi.tar.gz"
    m = cli.backup(settings, archive)
    assert m["issued_invoices"] == 1 and archive.stat().st_mode & 0o077 == 0
    db.get_engine().dispose()

    target = replace(settings, data_dir=tmp_path / "restored")
    cli.restore(target, archive)
    pdf = target.data_dir / issued.local_pdf_path
    assert sha256_file(pdf) == issued.local_pdf_sha256
    assert cli.verify(target)["ok"] is True
    with pytest.raises(SystemExit):
        cli.restore(target, archive)  # refuses to overwrite without --force


def test_restore_rejects_damaged_backup(settings, session, ready, tmp_path):
    import tarfile

    inv = svc.save_draft(session, None, practice_id=ready.id, lines=[line("2026-10-08")])
    issued = svc.issue(settings, inv.id, uuid.uuid4().hex).invoice
    good = tmp_path / "good.tar.gz"
    cli.backup(settings, good)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(good) as src, tarfile.open(bad, "w:gz") as dst:
        for m in src.getmembers():
            f = src.extractfile(m)
            if m.name == issued.local_pdf_path:
                import io

                data = b"tampered"
                m.size = len(data)
                dst.addfile(m, io.BytesIO(data))
            else:
                dst.addfile(m, f)
    with pytest.raises(SystemExit):
        cli.restore(replace(settings, data_dir=tmp_path / "r2"), bad)


def test_example_pdf_is_fictional(tmp_path):
    out = tmp_path / "ex.pdf"
    cli.main(["example-pdf", str(out)])
    from pypdf import PdfReader

    text = PdfReader(str(out)).pages[0].extract_text()
    assert "FICTIONAL EXAMPLE" in text and "£1,692.77" in text and "Page 1 of 1" in text


def test_backup_aborts_on_missing_or_altered_pdf(settings, session, ready, tmp_path):
    inv = svc.save_draft(session, None, practice_id=ready.id, lines=[line("2026-10-08")])
    issued = svc.issue(settings, inv.id, uuid.uuid4().hex).invoice
    pdf = settings.data_dir / issued.local_pdf_path
    dest = tmp_path / "b.tar.gz"
    pdf.write_bytes(b"altered")
    with pytest.raises(SystemExit):
        cli.backup(settings, dest)
    pdf.unlink()
    with pytest.raises(SystemExit):
        cli.backup(settings, dest)
    assert not dest.exists() and not list(tmp_path.glob("*.partial"))
