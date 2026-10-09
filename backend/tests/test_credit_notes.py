"""Credit notes: immutable, own series, exact pension maths, effects. Fictional data only."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from locuvi import integrity
from locuvi.errors import Conflict, DomainError
from locuvi.models import CreditNote
from locuvi.services import bank, core, credit_notes, diary, payments, pension, reports
from locuvi.services import invoices as svc


def issue_with(settings, s, practice, days, month="2026-08"):
    diary.add_sessions(
        s, [diary.SessionInput(practice.id, date.fromisoformat(f"{month}-{d:02d}")) for d in days]
    )
    d = diary.invoice_month(s, practice.id, month)
    inv = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    s.expire_all()
    return svc.get_invoice(s, inv.id)


def key():
    return uuid.uuid4().hex


def test_partial_then_full_credit_nets_to_zero(settings, session, ready):
    inv = issue_with(settings, session, ready, [3, 4, 5])  # 3 x 600, 90%, 14.38%
    assert inv.grand_total == Decimal("2032.96")
    l1, l2, l3 = [ln.id for ln in inv.lines]

    preview = credit_notes.compute(session, inv, [l1])
    assert preview.fee_subtotal == Decimal("600.00")
    assert preview.pensionable_pay == Decimal("540.00")
    assert preview.employer_contribution == Decimal("77.65")
    assert preview.grand_total == Decimal("677.65")

    cn1 = credit_notes.issue(settings, inv.id, [l1], "Session on 3 Aug cancelled", key())
    assert cn1.number == "CN-0001"
    session.commit()  # end the read snapshot; issue ran on its own connection
    session.expire_all()
    inv = svc.get_invoice(session, inv.id)
    st = payments.payment_state(inv)
    assert st["credited"] == "677.65" and st["outstanding"] == "1355.31"

    with pytest.raises(Conflict):
        credit_notes.issue(settings, inv.id, [l1], "again", key())
    cn2 = credit_notes.issue(settings, inv.id, [l2, l3], "Rest cancelled", key())
    assert cn2.number == "CN-0002"
    # last credit takes exactly what remains (1355.31 not 2 x 677.65 = 1355.30)
    assert cn2.grand_total == Decimal("1355.31")
    session.commit()  # end the read snapshot; issue ran on its own connection
    session.expire_all()
    inv = svc.get_invoice(session, inv.id)
    assert payments.payment_state(inv)["state"] == "credited"
    fig = pension.month_figures(session, "2026-08")
    assert fig["form_b"]["pensionable_pay"] == "0.00" and fig["form_b"]["employer"] == "0.00"
    assert fig["forms_a"][0]["credit_notes"] == ["CN-0001", "CN-0002"]


def test_credit_note_is_immutable_document(settings, session, ready):
    inv = issue_with(settings, session, ready, [3])
    cn = credit_notes.issue(settings, inv.id, [inv.lines[0].id], "Booked twice", "k" * 12)
    again = credit_notes.issue(settings, inv.id, [inv.lines[0].id], "Booked twice", "k" * 12)
    assert again.id == cn.id  # idempotent
    path = settings.data_dir / cn.local_pdf_path
    assert cn.local_pdf_path.startswith("invoices/credit/")
    text = "".join(p.extract_text() for p in PdfReader(path).pages)
    assert "CREDIT NOTE" in text and inv.invoice_number in text and "Booked twice" in text
    assert "Account number" not in text  # no payment details on a credit note
    # startup integrity keeps it (not quarantined) and verifies its checksum
    session.commit()  # fresh snapshot, as at startup
    res = integrity.check(session, settings)
    assert res["ok"] and res["quarantined"] == 0 and path.exists()
    path.write_bytes(b"tampered")
    assert integrity.check(session, settings, quarantine=False)["problems"][0]["problem"] == (
        "credit_pdf_checksum_mismatch"
    )
    with pytest.raises(Conflict):
        svc.void(session, svc.get_invoice(session, inv.id), "mistake")


def test_pdf_failure_does_not_consume_number(settings, session, ready):
    inv = issue_with(settings, session, ready, [3])

    def boom(_):
        raise RuntimeError("render failed")

    with pytest.raises(RuntimeError):
        credit_notes.issue(settings, inv.id, [inv.lines[0].id], "x", key(), render=boom)
    session.commit()  # end the read snapshot; issue ran on its own connection
    session.expire_all()
    assert session.query(CreditNote).count() == 0
    assert core.get_sequence(session).credit_next_number == 1


def test_credit_after_payment_and_reports(settings, session, ready):
    inv = issue_with(settings, session, ready, [3, 4])  # 1355.30
    payments.record_payment(session, inv, amount=Decimal("677.65"))
    credit_notes.issue(settings, inv.id, [inv.lines[1].id], "One session not worked", key())
    session.commit()  # end the read snapshot; issue ran on its own connection
    session.expire_all()
    inv = svc.get_invoice(session, inv.id)
    assert payments.payment_state(inv)["state"] == "paid"
    with pytest.raises(Conflict):
        payments.record_payment(session, inv, amount=Decimal("1.00"))
    assert all(i.id != inv.id for i, _ in bank._open_invoices(session))
    summ = reports.summary(session, reports.tax_year_of(core.today_london()))
    assert summ["totals"]["credited"] == "677.65"


def test_validation(settings, session, ready):
    inv = issue_with(settings, session, ready, [3])
    with pytest.raises(DomainError):
        credit_notes.issue(settings, inv.id, [inv.lines[0].id], "  ", key())
    with pytest.raises(DomainError):
        credit_notes.compute(session, inv, [])
    with pytest.raises(DomainError):
        credit_notes.compute(session, inv, ["not-a-line"])


def test_api_credit_notes(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        c.patch(
            "/api/v1/settings/profile",
            headers=h,
            json={
                "legal_name": "Dr Alex Example",
                "address_lines": "1 Sample Street",
                "postcode": "EX1 1AA",
                "email": "alex@example.invalid",
                "bank_account_holder": "Dr Alex Example",
                "bank_sort_code": "00-00-00",
                "bank_account_number": "00000000",
            },
        )
        p = c.post(
            "/api/v1/practices",
            headers=h,
            json={
                "name": "Example Medical Practice",
                "billing_address": "2 Test Road",
                "default_rate": "600.00",
            },
        ).json()
        c.post(
            "/api/v1/sessions",
            headers=h,
            json={"sessions": [{"practice_id": p["id"], "date": "2026-08-03"}]},
        )
        d = c.post(
            "/api/v1/sessions/invoice", headers=h, json={"practice_id": p["id"], "month": "2026-08"}
        ).json()
        r = c.post(f"/api/v1/invoices/{d['id']}/issue", headers={**h, "Idempotency-Key": key()})
        assert r.status_code in (200, 201), r.text
        line = c.get(f"/api/v1/invoices/{d['id']}").json()["lines"][0]["id"]
        pv = c.post(
            f"/api/v1/invoices/{d['id']}/credit-notes/preview", headers=h, json={"line_ids": [line]}
        ).json()
        assert pv.get("grand_total") == "677.65", pv
        r = c.post(
            f"/api/v1/invoices/{d['id']}/credit-notes",
            json={"line_ids": [line], "reason": "Cancelled"},
            headers={**h, "Idempotency-Key": key()},
        )
        assert r.status_code == 201
        detail = c.get(f"/api/v1/invoices/{d['id']}").json()
        assert detail["credit_notes"][0]["number"] == "CN-0001"
        assert detail["payment"]["state"] == "credited"
        pdf = c.get(f"/api/v1/credit-notes/{r.json()['id']}/pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_refund_owed_after_credit_on_paid_invoice(settings, session, ready):
    from locuvi.services import checks

    inv = issue_with(settings, session, ready, [3, 4])  # 1355.30
    payments.record_payment(session, inv)  # paid in full
    credit_notes.issue(settings, inv.id, [inv.lines[1].id], "Second session cancelled", key())
    session.commit()
    session.expire_all()
    inv = svc.get_invoice(session, inv.id)
    st = payments.payment_state(inv)
    assert st["state"] == "refund_due" and st["refund_due"] == "677.65"
    found = {f.kind: f for f in checks.run_checks(session)}
    assert found["refund_due"].params["refund"] == "677.65"
    with pytest.raises(DomainError):
        payments.record_refund(session, inv, amount=Decimal("700.00"))
    payments.record_refund(session, inv, paid_on=core.today_london())
    session.expire_all()
    inv = svc.get_invoice(session, inv.id)
    assert payments.payment_state(inv)["state"] == "paid"
    assert "refund_due" not in {f.kind for f in checks.run_checks(session)}
    with pytest.raises(Conflict):
        payments.record_refund(session, inv)
    # cash basis nets the refund off; Form B takes the employer share back
    summ = reports.summary(session, reports.tax_year_of(core.today_london()), "cash")
    assert summ["totals"]["income"] == "677.65"
    month = core.today_london().strftime("%Y-%m")
    b = pension.month_figures(session, month)["form_b"]
    assert b["pensionable_pay"] == "540.00" and b["employer"] == "77.65"
