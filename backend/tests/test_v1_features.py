import email
import io
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_practice
from pypdf import PdfReader

from locuvi import db, mail
from locuvi.errors import Conflict, DomainError
from locuvi.models import Invoice, WorkSession
from locuvi.secrets_store import SecretBox
from locuvi.services import core, diary, payments, pension, reports
from locuvi.services import invoices as svc


def add(s, practice, *days, unit="am", **kw):
    return diary.add_sessions(s, [diary.SessionInput(practice.id, d, unit, **kw) for d in days])


def issue(settings, inv_id):
    return svc.issue(settings, inv_id, uuid.uuid4().hex).invoice


# ------------------------------------------------------------------ diary


def test_sessions_remember_rate_and_defaults(session, ready):
    a = add(session, ready, date(2026, 10, 1))[0]
    assert a.rate == Decimal("600.00") and a.pensionable and a.description == "GP locum AM session"
    add(session, ready, date(2026, 10, 2), rate=Decimal("575.00"))
    b = add(session, ready, date(2026, 10, 3))[0]
    assert b.rate == Decimal("575.00")  # remembers last used AM rate
    pm = ready.default_rate
    c = add(session, ready, date(2026, 10, 3), unit="pm")[0]
    assert c.rate == pm and c.description == "GP locum PM session"


def test_rate_required_once(session, ready):
    p = make_practice(session, name="No Rate Practice")
    p.default_rate = None
    session.commit()
    with pytest.raises(DomainError):
        add(session, p, date(2026, 10, 1))


def test_month_to_invoice_flow(settings, session, ready):
    add(session, ready, date(2026, 9, 1), date(2026, 9, 8))
    add(session, ready, date(2026, 9, 9), unit="pm", rate=Decimal("550.00"))
    add(session, ready, date(2026, 8, 2))  # other month
    future = core.today_london() + timedelta(days=5)
    add(session, ready, future)  # booked, not worked yet
    groups = diary.ready_to_invoice(session)
    assert all(g["month"] != f"{future:%Y-%m}" or g["sessions"] for g in groups)
    oct_ = next(g for g in groups if g["month"] == "2026-09")
    assert oct_["sessions"] == 3 and oct_["total"] == "1750.00"
    draft = diary.invoice_month(session, ready.id, "2026-09")
    assert draft.status == "draft" and len(draft.lines) == 3
    assert draft.grand_total == Decimal("1976.49")  # 1750*.9=1575; *.1438=226.485 -> 226.49
    assert all(g["month"] != "2026-09" for g in diary.ready_to_invoice(session))
    # a late-added September session joins the same draft
    add(session, ready, date(2026, 9, 15))
    again = diary.invoice_month(session, ready.id, "2026-09")
    assert again.id == draft.id and len(again.lines) == 4
    inv = issue(settings, draft.id)
    ws = session.query(WorkSession).filter(WorkSession.invoice_id == inv.id).count()
    assert ws == 4
    s = db.new_session()
    w = s.query(WorkSession).filter(WorkSession.invoice_id == inv.id).first()
    with pytest.raises(Conflict):
        diary.update_session(s, w, rate=Decimal("1"))
    # void releases sessions so they can be invoiced again
    svc.void(s, s.get(Invoice, inv.id), "wrong month")
    assert any(g["month"] == "2026-09" for g in diary.ready_to_invoice(db.new_session()))


def test_deleting_draft_releases_sessions(session, ready):
    add(session, ready, date(2026, 10, 1))
    d = diary.invoice_month(session, ready.id, "2026-10")
    svc.delete_draft(session, d)
    assert diary.ready_to_invoice(session)[0]["sessions"] == 1


def test_nothing_to_invoice(session, ready):
    with pytest.raises(DomainError):
        diary.invoice_month(session, ready.id, "2026-10")


# --------------------------------------------------------------- payments


def _issued(settings, session, ready, d=date(2026, 9, 1)):
    add(session, ready, d)
    return issue(settings, diary.invoice_month(session, ready.id, f"{d:%Y-%m}").id)


def test_payments_full_part_overdue(settings, session, ready):
    inv = _issued(settings, session, ready)
    s = db.new_session()
    inv = s.get(Invoice, inv.id)
    st = payments.payment_state(inv, inv.due_date)
    assert st["state"] == "unpaid" and st["outstanding"] == "677.65"
    assert payments.payment_state(inv, inv.due_date + timedelta(days=3))["days_overdue"] == 3
    payments.record_payment(s, inv, amount=Decimal("100.00"))
    assert payments.payment_state(inv, inv.due_date)["state"] == "part_paid"
    with pytest.raises(DomainError):
        payments.record_payment(s, inv, amount=Decimal("600.00"))
    payments.record_payment(s, inv)  # one tap: the rest
    st = payments.payment_state(inv)
    assert st["state"] == "paid" and st["outstanding"] == "0.00"
    with pytest.raises(Conflict):
        payments.record_payment(s, inv)
    with pytest.raises(Conflict):
        svc.void(s, inv, "x")  # paid invoices can't be voided
    assert inv.immutable_snapshot_json["totals"]["grand_total"] == "677.65"  # invoice untouched
    payments.delete_payment(s, inv.payments[0].id)
    assert payments.payment_state(inv)["state"] in {"part_paid", "overdue"}


# ---------------------------------------------------------------- pension


def test_pension_month_figures_and_submission(settings, session, ready):
    other = make_practice(session, name="Second Example Surgery")
    other.practice_code = "X00000"
    session.commit()
    _issued(settings, session, ready, date(2026, 9, 3))
    add(session, other, date(2026, 9, 10), date(2026, 9, 11))
    issue(settings, diary.invoice_month(session, other.id, "2026-09").id)
    p = core.get_profile(session)
    p.employee_rate = Decimal("0.098")
    session.commit()
    fig = pension.month_figures(session, "2026-09")
    assert len(fig["forms_a"]) == 2
    b = fig["form_b"]
    assert b["pensionable_pay"] == "1620.00"  # 540 + 1080
    assert b["employer"] == "232.95"  # 77.65 + 155.30
    assert b["employee"] == "158.76"  # 1620 * 0.098
    assert b["total_payable"] == "391.71"
    pdf = PdfReader(
        io.BytesIO(__import__("locuvi.pdf.pension", fromlist=["x"]).render_pension_worksheet(fig))
    )
    text = pdf.pages[0].extract_text()
    assert "September 2026" in text and "X00000" in text and "£391.71" in text
    assert "not a submission" in text
    row = next(m for m in pension.overview(session) if m["month"] == "2026-09")
    assert row["submitted_on"] is None and row["ready"]
    pension.mark_submitted(session, "2026-09")
    with pytest.raises(Conflict):
        pension.mark_submitted(session, "2026-09")
    row = next(m for m in pension.overview(session) if m["month"] == "2026-09")
    assert row["submitted_on"] and not row["changed_since_submitted"]


def test_non_pensionable_invoice_not_in_pension(settings, session, ready):
    add(session, ready, date(2026, 8, 3), pensionable=False)
    issue(settings, diary.invoice_month(session, ready.id, "2026-08").id)
    assert pension.month_figures(session, "2026-08")["forms_a"] == []


# ---------------------------------------------------------------- reports


def test_tax_year_bounds():
    assert reports.tax_year_of(date(2026, 4, 5)) == 2025
    assert reports.tax_year_of(date(2026, 4, 6)) == 2026
    assert reports.tax_year_bounds(2026) == (date(2026, 4, 6), date(2027, 4, 5))


def test_summary_csv_pack(settings, session, ready):
    inv = _issued(settings, session, ready)
    s = db.new_session()
    payments.record_payment(s, s.get(Invoice, inv.id))
    year = reports.tax_year_of(inv.invoice_date)
    summ = reports.summary(s, year)
    assert summ["totals"]["invoiced"] == "677.65" and summ["totals"]["paid"] == "677.65"
    assert summ["totals"]["employer"] == "77.65" and len(summ["months"]) == 13  # 6 Apr – 5 Apr
    start, end = reports.tax_year_bounds(year)
    csv_text = reports.invoices_csv(s, start, end)
    assert "LOC-2026-0001" in csv_text and "677.65" in csv_text and "00000000" not in csv_text
    z = zipfile.ZipFile(io.BytesIO(reports.year_pack(s, settings, year)))
    assert "invoices/LOC-2026-0001.pdf" in z.namelist()


def test_today_overview(settings, session, ready):
    add(session, ready, date(2026, 10, 1))
    ov = reports.today_overview(session)
    assert ov["ready_to_invoice"][0]["sessions"] == 1
    _issued(settings, session, ready, date(2026, 9, 2))
    ov = reports.today_overview(db.new_session())
    assert ov["unpaid"][0]["invoice_number"] == "LOC-2026-0001"


# ------------------------------------------------------------------ email


class FakeSMTP:
    sent: list = []

    def __init__(self, cfg):
        self.cfg = cfg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        if pw != "smtp-secret":
            import smtplib

            raise smtplib.SMTPAuthenticationError(535, b"no")

    def send_message(self, msg, from_addr, to_addrs):
        FakeSMTP.sent.append((msg, to_addrs))


def test_email_invoice(settings, session, ready, monkeypatch):
    monkeypatch.setattr(mail, "resolve_and_check", lambda *a: None)
    box = SecretBox(settings)
    ready.billing_email = "accounts@example.invalid"
    session.commit()
    inv = _issued(settings, session, ready)
    s = db.new_session()
    inv = s.get(Invoice, inv.id)
    with pytest.raises(DomainError):
        mail.send_invoice(s, settings, box, inv, to="a@example.invalid", subject="x", body="y")
    mail.save_config(
        s,
        box,
        {
            "enabled": True,
            "host": "smtp.example.invalid",
            "port": 587,
            "security": "starttls",
            "username": "u",
            "password": "smtp-secret",
            "from_address": "me@example.invalid",
        },
    )
    assert "smtp-secret" not in str(mail.config_public(mail.get_config(s)))
    d = mail.draft_for(s, inv)
    assert d["to"] == "accounts@example.invalid" and "LOC-2026-0001" in d["subject"]
    FakeSMTP.sent.clear()
    res = mail.send_invoice(
        s,
        settings,
        box,
        inv,
        to=d["to"],
        subject=d["subject"],
        body=d["body"],
        smtp_factory=FakeSMTP,
    )
    msg, rcpts = FakeSMTP.sent[0]
    assert rcpts == ["accounts@example.invalid", "me@example.invalid"]  # bcc self
    parsed = email.message_from_bytes(msg.as_bytes())
    att = [p for p in parsed.walk() if p.get_filename()]
    assert att[0].get_filename() == "LOC-2026-0001.pdf"
    assert res["sent_to"] == ["accounts@example.invalid"] and inv.last_emailed_at
    with pytest.raises(DomainError):
        mail.send_invoice(
            s, settings, box, inv, to="not-an-email", subject="x", body="y", smtp_factory=FakeSMTP
        )
    mail.save_config(
        s,
        box,
        {
            "enabled": True,
            "host": "smtp.example.invalid",
            "port": 587,
            "security": "starttls",
            "username": "u",
            "password": "wrong",
            "from_address": "me@example.invalid",
        },
    )
    with pytest.raises(DomainError) as ei:
        mail.send_invoice(
            s, settings, box, inv, to=d["to"], subject="x", body="y", smtp_factory=FakeSMTP
        )
    assert ei.value.code == "email.auth_failed"


# ---------------------------------------------------------- API smoke


def test_api_new_endpoints(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        csrf = c.get("/api/v1/auth/session").json()["csrf_token"]
        h = {"X-CSRF-Token": csrf}
        assert c.get("/api/v1/overview").json()["setup"]["completed"] is False
        r = c.patch("/api/v1/settings/profile", json={"legal_name": "Dr Alex Example"}, headers=h)
        assert r.json()["legal_name"] == "Dr Alex Example"
        r = c.patch("/api/v1/settings/profile", json={"postcode": "EX1 1AA"}, headers=h)
        assert r.json()["legal_name"] == "Dr Alex Example"  # partial update kept name
        p = c.post(
            "/api/v1/practices",
            json={
                "name": "Example Medical Practice",
                "billing_address": "2 Test Road",
                "default_rate": "600.00",
            },
            headers=h,
        ).json()
        r = c.post(
            "/api/v1/sessions",
            json={
                "sessions": [
                    {"practice_id": p["id"], "date": "2026-10-01"},
                    {"practice_id": p["id"], "date": "2026-10-02", "unit": "pm"},
                ]
            },
            headers=h,
        )
        assert r.status_code == 201 and r.json()[1]["rate"] == "600.00"
        lst = c.get("/api/v1/sessions?start=2026-10-01&end=2026-10-31").json()
        assert len(lst) == 2
        r = c.post(
            "/api/v1/sessions/invoice", json={"practice_id": p["id"], "month": "2026-10"}, headers=h
        )
        assert r.status_code == 201 and r.json()["grand_total"] == "1355.30"
        assert c.get("/api/v1/pension").status_code == 200
        assert c.get("/api/v1/reports/summary").json()["label"]
        assert c.get("/api/v1/pension/2026-13").status_code == 400
        assert c.get("/api/v1/settings/email").json()["password_set"] is False
