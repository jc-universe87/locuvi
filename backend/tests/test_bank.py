"""Bank statement import and deterministic matching. Fictional data only."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from conftest import make_practice

from locuvi.errors import DomainError
from locuvi.models import BankTransaction, Payment
from locuvi.services import bank, checks, core, diary, payments
from locuvi.services import invoices as svc


def issue(settings, s, practice, month, days):
    diary.add_sessions(
        s, [diary.SessionInput(practice.id, date.fromisoformat(f"{month}-{d:02d}")) for d in days]
    )
    d = diary.invoice_month(s, practice.id, month)
    inv = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    s.expire_all()
    return svc.get_invoice(s, inv.id)


@pytest.mark.parametrize(
    "csv_text",
    [
        # Lloyds-style: separate debit/credit columns
        "Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,"
        "Debit Amount,Credit Amount,Balance\n"
        "03/10/2026,FPI,'00-00-00,00000000,EXAMPLE MEDICAL REF X,,677.65,1000.00\n"
        "02/10/2026,DEB,'00-00-00,00000000,COFFEE SHOP,3.20,,322.35\n",
        # Nationwide-style with £ signs
        "Date,Transaction type,Description,Paid out,Paid in,Balance\n"
        "03 Oct 2026,Bank credit,EXAMPLE MEDICAL REF X,,£677.65,£1000.00\n"
        "02 Oct 2026,Payment to,COFFEE SHOP,£3.20,,£322.35\n",
        # Monzo/Starling-style signed amount
        "Date,Name,Reference,Amount (GBP),Balance\n"
        "2026-10-03,Example Medical,REF X,677.65,1000.00\n2026-10-02,Coffee Shop,,-3.20,322.35\n",
        # headerless (date, description, amount)
        "03/10/2026,EXAMPLE MEDICAL REF X,677.65\n02/10/2026,COFFEE SHOP,-3.20\n",
    ],
)
def test_parse_formats_keep_only_credits(csv_text):
    rows = bank.parse_statement(csv_text.encode())
    assert len(rows) == 1
    (r,) = rows
    assert r["booked_on"] == date(2026, 10, 3) and r["amount"] == Decimal("677.65")
    assert "COFFEE" not in r["description"].upper()


def test_parse_amount_edge_cases():
    assert bank.parse_amount("£1,234.50") == Decimal("1234.50")
    assert bank.parse_amount("(12.00)") == Decimal("-12.00")
    assert bank.parse_amount("50.00 DR") == Decimal("-50.00")
    assert bank.parse_amount("50.00CR") == Decimal("50.00")
    assert bank.parse_amount("abc") is None and bank.parse_amount("NaN") is None


def test_match_by_number_amount_and_combined(settings, session, ready):
    other = make_practice(session, name="Riverside Surgery")
    a = issue(settings, session, ready, "2026-08", [3])  # £677.65
    b = issue(settings, session, ready, "2026-09", [3, 4])  # £1355.30
    c = issue(settings, session, other, "2026-08", [5])  # £677.65 (same amount as a!)
    d = issue(settings, session, other, "2026-09", [6])  # £677.65
    today = core.today_london()
    day = today.strftime("%d/%m/%Y")  # payments arrive after the invoices are issued
    csv_text = (
        "Date,Description,Amount\n"
        f"{day},BACS {a.invoice_number} THANK YOU,677.65\n"  # number -> a
        f"{day},EXAMPLE MEDICAL PRACTICE,1355.30\n"  # exact amount of b, practice named
        f"{day},RIVERSIDE SURG PAYMENT,1355.30\n"  # c + d combined
        f"{day},UNKNOWN PAYER,99.00\n"
    )
    res = bank.import_statement(session, "oct.csv", csv_text.encode())
    assert res["new"] == 4 and res["suggested"] == 3 and res["unmatched"] == 1
    txs = {t.description: t for t in session.query(BankTransaction).all()}
    s1 = txs[f"BACS {a.invoice_number} THANK YOU"].suggestion_json
    assert s1["kind"] == "number" and s1["invoices"][0]["id"] == a.id
    s2 = txs["EXAMPLE MEDICAL PRACTICE"].suggestion_json
    assert s2["kind"] == "amount_practice" and s2["invoices"][0]["id"] == b.id
    s3 = txs["RIVERSIDE SURG PAYMENT"].suggestion_json
    assert s3["kind"] == "combined" and {i["id"] for i in s3["invoices"]} == {c.id, d.id}
    assert s3["confidence"] == "high"  # "Riverside" named

    # importing the same file again adds nothing
    again = bank.import_statement(session, "oct.csv", csv_text.encode())
    assert again["new"] == 0 and again["duplicates"] == 4

    assert bank.accept_all(session) == 3
    session.expire_all()
    for inv in (a, b, c, d):
        assert payments.payment_state(svc.get_invoice(session, inv.id))["state"] == "paid"
    pay = session.query(Payment).filter(Payment.invoice_id == a.id).one()
    assert pay.paid_on == today and pay.method == "bank_transfer"

    # undo removes the recorded payments
    t1 = txs[f"BACS {a.invoice_number} THANK YOU"]
    bank.undo(session, t1)
    session.expire_all()
    assert payments.payment_state(svc.get_invoice(session, a.id))["state"] != "paid"
    assert t1.status == "suggested"  # suggestion comes back


def test_ambiguous_amount_is_not_guessed(settings, session, ready):
    other = make_practice(session, name="Riverside Surgery")
    issue(settings, session, ready, "2026-08", [3])
    issue(settings, session, other, "2026-08", [5])
    day = core.today_london().strftime("%d/%m/%Y")
    bank.import_statement(session, "x.csv", f"Date,Description,Amount\n{day},FPS,677.65\n".encode())
    (tx,) = session.query(BankTransaction).all()
    assert tx.status == "unmatched"  # two invoices owe 677.65 and nothing names either
    assert "bank_unmatched" in {f.kind for f in checks.run_checks(session)}
    with pytest.raises(DomainError):
        bank.accept(session, tx)


def test_manual_match_part_payment_and_ignore(settings, session, ready):
    inv = issue(settings, session, ready, "2026-08", [3])
    csv_text = b"Date,Description,Amount\n01/10/2026,FPS,300.00\n02/10/2026,REFUND,5.00\n"
    bank.import_statement(session, "x.csv", csv_text)
    part, refund = sorted(
        session.query(BankTransaction).all(), key=lambda t: t.amount, reverse=True
    )
    bank.accept(session, part, [inv.id])
    session.expire_all()
    st = payments.payment_state(svc.get_invoice(session, inv.id))
    assert st["state"] == "part_paid" and st["outstanding"] == "377.65"
    bank.ignore(session, refund)
    assert refund.status == "ignored"
    bank.undo(session, refund)
    assert refund.status in {"unmatched", "suggested"}


def test_bad_files(session):
    with pytest.raises(DomainError):
        bank.parse_statement(b"")
    with pytest.raises(DomainError):
        bank.parse_statement(b"Date,Description\n01/10/2026,x\n")
    with pytest.raises(DomainError):
        bank.parse_statement(b"x" * (bank.MAX_BYTES + 1))


def test_api_bank_flow(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        r = c.post(
            "/api/v1/bank/import",
            headers=h,
            files={
                "file": ("s.csv", b"Date,Description,Amount\n01/10/2026,FPS,10.00\n", "text/csv")
            },
        )
        assert r.status_code == 201 and r.json()["unmatched"] == 1
        lst = c.get("/api/v1/bank/transactions").json()
        tx = lst["transactions"][0]
        assert tx["amount"] == "10.00"
        assert (
            c.post(f"/api/v1/bank/transactions/{tx['id']}/ignore", headers=h).json()["status"]
            == "ignored"
        )
        assert c.post("/api/v1/bank/transactions/accept-all", headers=h).json()["recorded"] == 0
        assert c.get("/api/v1/bank/transactions?status=bogus").status_code == 400


def test_combined_match_is_all_or_nothing(settings, session, ready, monkeypatch):
    """A failure (or crash) part-way through a multi-invoice match leaves nothing recorded."""
    from locuvi import db
    from locuvi.models import Payment

    other = make_practice(session, name="Riverside Surgery")
    c = issue(settings, session, other, "2026-08", [5])
    d = issue(settings, session, other, "2026-09", [6])
    day = core.today_london().strftime("%d/%m/%Y")
    bank.import_statement(
        session, "x.csv", f"Date,Description,Amount\n{day},RIVERSIDE SURGERY,1355.30\n".encode()
    )
    tx = session.query(BankTransaction).one()
    assert tx.suggestion_json["kind"] == "combined"

    real = payments.record_payment
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated crash after the first payment")
        return real(*a, **kw)

    monkeypatch.setattr(payments, "record_payment", flaky)
    with pytest.raises(RuntimeError):
        bank.accept(session, tx)
    other_conn = db.new_session()  # what another process would see
    assert other_conn.query(Payment).count() == 0
    assert other_conn.get(BankTransaction, tx.id).status == "suggested"
    other_conn.close()

    monkeypatch.setattr(payments, "record_payment", real)
    session.expire_all()
    bank.accept(session, session.get(BankTransaction, tx.id))
    check = db.new_session()
    assert check.query(Payment).count() == 2
    assert check.get(BankTransaction, tx.id).status == "matched"
    check.close()
    for inv in (c, d):
        session.expire_all()
        assert payments.payment_state(svc.get_invoice(session, inv.id))["state"] == "paid"


def test_stale_suggestion_fails_cleanly(settings, session, ready):
    """If an invoice was paid by hand after the suggestion, confirming records nothing."""
    from locuvi.models import Payment

    inv = issue(settings, session, ready, "2026-08", [3])
    day = core.today_london().strftime("%d/%m/%Y")
    bank.import_statement(
        session,
        "x.csv",
        f"Date,Description,Amount\n{day},BACS {inv.invoice_number},677.65\n".encode(),
    )
    tx = session.query(BankTransaction).one()
    payments.record_payment(session, svc.get_invoice(session, inv.id))  # paid by hand meanwhile
    from locuvi.errors import Conflict

    with pytest.raises(Conflict):  # "Nothing is owed on this invoice."
        bank.accept(session, tx)
    assert session.query(Payment).count() == 1 and tx.status == "suggested"
