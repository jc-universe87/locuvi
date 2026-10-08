import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from conftest import line, make_practice
from locuvi import db
from locuvi.errors import Conflict, DomainError, ValidationFailed
from locuvi.models import Invoice, InvoiceStatus
from locuvi.services import core
from locuvi.services import invoices as svc
from locuvi.storage.local import sha256_file


def key() -> str:
    return uuid.uuid4().hex


def draft(s, practice, lines=None, **kw):
    lines = lines or [line("2026-10-08"), line("2026-10-15", price="650.00",
                                               desc="GP locum PM session", unit="pm")]
    return svc.save_draft(s, None, practice_id=practice.id, lines=lines,
                          invoice_date=date(2026, 10, 20), **kw)


def pdf_text(settings, inv) -> str:
    reader = PdfReader(str(settings.data_dir / inv.local_pdf_path))
    return "\n".join(p.extract_text() for p in reader.pages)


def test_two_october_sessions_issue(settings, session, ready):
    inv = draft(session, ready)
    assert inv.invoice_number is None and inv.status == "draft"
    assert inv.grand_total == Decimal("1411.78")  # 1250 -> 1125 pay -> 161.775 -> 161.78
    res = svc.issue(settings, inv.id, key())
    inv = res.invoice
    assert inv.status == InvoiceStatus.issued
    assert inv.invoice_number == "LOC-2026-0001"
    assert inv.employer_contribution == Decimal("161.78")
    assert inv.due_date == date(2026, 11, 19)
    path = settings.data_dir / inv.local_pdf_path
    assert sha256_file(path) == inv.local_pdf_sha256
    text = pdf_text(settings, inv)
    for needle in ["INVOICE", "LOC-2026-0001", "Dr Alex Example", "Example Medical Practice",
                   "20 October 2026", "19 November 2026", "£1,411.78", "£161.78",
                   "00-00-00", "00000000", "Page 1 of 1", "14.38%"]:
        assert needle in text, needle


def test_numbering_sequential_and_unique(settings, session, ready):
    nums = []
    for _ in range(3):
        inv = draft(session, ready, lines=[line("2026-10-01")])
        nums.append(svc.issue(settings, inv.id, key()).invoice.invoice_number)
    assert nums == ["LOC-2026-0001", "LOC-2026-0002", "LOC-2026-0003"]


def test_idempotent_replay_and_conflict(settings, session, ready):
    inv = draft(session, ready)
    k = key()
    a = svc.issue(settings, inv.id, k)
    b = svc.issue(settings, inv.id, k)
    assert b.replayed and b.invoice.invoice_number == a.invoice.invoice_number
    with pytest.raises(Conflict):
        svc.issue(settings, inv.id, key())
    assert core.get_sequence(db.new_session()).next_number == 2


def test_parallel_issue_cannot_issue_twice(settings, session, ready):
    inv = draft(session, ready)
    k = key()
    results, errors = [], []

    def worker(k2):
        try:
            results.append(svc.issue(settings, inv.id, k2))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(k if i % 2 else key(),)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s = db.new_session()
    issued = s.query(Invoice).filter(Invoice.status == "issued").all()
    assert len(issued) == 1
    assert core.get_sequence(s).next_number == 2
    assert all(isinstance(e, Conflict) for e in errors)
    assert {r.invoice.invoice_number for r in results} == {"LOC-2026-0001"}


def test_parallel_issue_of_different_drafts_unique_numbers(settings, session, ready):
    drafts = [draft(session, ready, lines=[line("2026-10-02")]).id for _ in range(6)]
    out = []
    threads = [threading.Thread(target=lambda i=i: out.append(
        svc.issue(settings, i, key()).invoice.invoice_number)) for i in drafts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == [f"LOC-2026-{n:04d}" for n in range(1, 7)]


def test_pdf_failure_does_not_consume_number(settings, session, ready):
    inv = draft(session, ready)

    def boom(_snap):
        raise RuntimeError("renderer crashed")

    with pytest.raises(RuntimeError):
        svc.issue(settings, inv.id, key(), render=boom)
    s = db.new_session()
    assert s.get(Invoice, inv.id).status == "draft"
    assert core.get_sequence(s).next_number == 1
    res = svc.issue(settings, inv.id, key())
    assert res.invoice.invoice_number == "LOC-2026-0001"


def test_snapshot_and_pdf_unchanged_after_settings_edit(settings, session, ready):
    inv = svc.issue(settings, draft(session, ready).id, key()).invoice
    before = sha256_file(settings.data_dir / inv.local_pdf_path)
    snap_before = dict(inv.immutable_snapshot_json)
    s = db.new_session()
    p = core.get_profile(s)
    p.bank_account_number = "11111111"
    p.legal_name = "Changed Name"
    pr = s.get(type(ready), ready.id)
    pr.name = "Renamed Practice"
    s.commit()
    s2 = db.new_session()
    again = s2.get(Invoice, inv.id)
    assert again.immutable_snapshot_json == snap_before
    assert again.immutable_snapshot_json["bank"]["account_number"] == "00000000"
    assert sha256_file(settings.data_dir / again.local_pdf_path) == before
    with pytest.raises(Conflict):
        svc.save_draft(s2, again, notes="edit")


def test_pensionable_multi_month_blocked_and_split(settings, session, ready):
    inv = draft(session, ready, lines=[line("2026-10-30"), line("2026-11-02")])
    with pytest.raises(ValidationFailed) as ei:
        svc.issue(settings, inv.id, key())
    codes = [p["code"] for p in ei.value.params["problems"]]
    assert "invoice.pensionable_multi_month" in codes
    parts = svc.split_by_month(session, inv)
    assert len(parts) == 2
    assert [len(p.lines) for p in parts] == [1, 1]
    for p in parts:
        svc.issue(settings, p.id, key())


def test_non_pensionable_multi_month_permitted(settings, session, ready):
    inv = draft(session, ready, lines=[line("2026-10-30", pensionable=False),
                                       line("2026-11-02", pensionable=False)])
    a = svc.analyse(session, lines=inv.lines, pension_enabled=True, practice=ready)
    assert [w.code for w in a.warnings][:1] == ["invoice.lines_multi_month"]
    assert svc.issue(settings, inv.id, key()).invoice.grand_total == Decimal("1200.00")


def test_preflight_requires_profile_and_vat_block(settings, session):
    pr = make_practice(session)
    inv = draft(session, pr)
    with pytest.raises(ValidationFailed) as ei:
        svc.issue(settings, inv.id, key())
    assert "profile.incomplete" in [p["code"] for p in ei.value.params["problems"]]
    from conftest import fill_profile
    fill_profile(session)
    core.get_profile(session).vat_status = "vat_registered"
    session.commit()
    with pytest.raises(ValidationFailed) as ei:
        svc.issue(settings, inv.id, key())
    assert "invoice.vat_unsupported" in [p["code"] for p in ei.value.params["problems"]]


def test_inclusive_rate_warning(session, ready):
    ready.rate_includes_pension = True
    session.commit()
    inv = draft(session, ready)
    a = svc.analyse(session, lines=inv.lines, pension_enabled=True, practice=ready)
    assert "invoice.practice_rate_inclusive" in [w.code for w in a.warnings]


def test_void_keeps_number_and_pdf(settings, session, ready):
    inv = svc.issue(settings, draft(session, ready).id, key()).invoice
    s = db.new_session()
    inv = s.get(Invoice, inv.id)
    with pytest.raises(DomainError):
        svc.void(s, inv, "  ")
    svc.void(s, inv, "Wrong practice")
    assert inv.status == "voided" and inv.invoice_number == "LOC-2026-0001"
    assert (settings.data_dir / inv.local_pdf_path).exists()
    nxt = svc.issue(settings, draft(s, ready).id, key()).invoice
    assert nxt.invoice_number == "LOC-2026-0002"  # voided number never reused


def test_duplicate_creates_fresh_draft(settings, session, ready):
    inv = svc.issue(settings, draft(session, ready).id, key()).invoice
    s = db.new_session()
    dup = svc.duplicate(s, s.get(Invoice, inv.id))
    assert dup.status == "draft" and dup.invoice_number is None
    assert len(dup.lines) == 2 and dup.id != inv.id


def test_preview_has_no_number(settings, session, ready):
    inv = draft(session, ready)
    pdf = svc.preview_pdf(session, inv)
    import io
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "DRAFT" in text and "LOC-2026" not in text
    assert core.get_sequence(session).next_number == 1


def test_multi_page_pdf_has_page_numbers(settings, session, ready):
    lines = [line(f"2026-10-{d:02d}", desc=f"Session {i} " + "with notes " * 6)
             for i, d in enumerate([*range(1, 31)] * 2)]
    inv = draft(session, ready, lines=lines)
    res = svc.issue(settings, inv.id, key()).invoice
    reader = PdfReader(str(settings.data_dir / res.local_pdf_path))
    n = len(reader.pages)
    assert n >= 2
    last = reader.pages[-1].extract_text()
    assert f"Page {n} of {n}" in last and "Total due" in last


def test_policy_versioning_new_rate(settings, session, ready):
    from locuvi.models import PensionPolicy
    session.add(PensionPolicy(effective_from=date(2027, 4, 1), pensionable_fraction=Decimal("0.90"),
                              employer_rate=Decimal("0.1500"), label="test"))
    session.commit()
    inv = draft(session, ready, lines=[line("2027-04-05")])
    assert inv.employer_contribution == Decimal("81.00")  # 540 * 0.15
    old = draft(session, ready, lines=[line("2027-03-05")])
    assert old.employer_contribution == Decimal("77.65")
