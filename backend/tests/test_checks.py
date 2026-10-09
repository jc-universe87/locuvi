import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from conftest import make_practice

from locuvi import cli, db, mail
from locuvi.models import Invoice
from locuvi.secrets_store import SecretBox
from locuvi.services import checks, core, diary, digest, payments, pension, reports
from locuvi.services import invoices as svc

TODAY = date(2026, 10, 8)


def add(s, practice, *days, unit="am", **kw):
    return diary.add_sessions(s, [diary.SessionInput(practice.id, d, unit, **kw) for d in days])


def kinds(s, settings=None, today=TODAY):
    return {f.kind for f in checks.run_checks(s, settings, today=today)}


def issue_month(settings, s, practice, month):
    d = diary.invoice_month(s, practice.id, month)
    inv = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    s.expire_all()  # issue ran in its own transaction
    return inv


def test_empty_install_has_no_findings(session):
    assert checks.run_checks(session, today=TODAY) == []


def test_uninvoiced_month_and_current(session, ready):
    add(session, ready, date(2026, 9, 3), date(2026, 10, 1))
    found = {f.kind: f for f in checks.run_checks(session, today=TODAY)}
    assert found["uninvoiced_month"].severity == "warn"
    assert found["uninvoiced_month"].action == {
        "type": "create_invoice",
        "practice_id": ready.id,
        "month": "2026-09",
    }
    assert found["uninvoiced_current"].severity == "info"


def test_duplicate_and_overlap(session, ready):
    other = make_practice(session, name="Second Example Surgery")
    add(session, ready, date(2026, 9, 3))
    add(session, ready, date(2026, 9, 3))  # duplicate
    add(session, ready, date(2026, 9, 4), unit="day")
    add(session, other, date(2026, 9, 4), unit="pm")  # overlaps full day
    add(session, ready, date(2026, 9, 5), unit="am")
    add(session, other, date(2026, 9, 5), unit="pm")  # AM + PM elsewhere is fine
    found = checks.run_checks(session, today=TODAY)
    assert [f.params["date"] for f in found if f.kind == "session_duplicate"] == ["2026-09-03"]
    assert [f.params["date"] for f in found if f.kind == "session_overlap"] == ["2026-09-04"]


def test_overdue_severity_and_payment_clears(settings, session, ready):
    add(session, ready, date(2026, 9, 3))
    inv = issue_month(settings, session, ready, "2026-09")
    due = inv.due_date
    assert "invoice_awaiting" in kinds(session, today=due - timedelta(days=10))
    assert "invoice_due_soon" in kinds(session, today=due - timedelta(days=2))
    f = next(
        x
        for x in checks.run_checks(session, today=due + timedelta(days=3))
        if x.kind == "invoice_overdue"
    )
    assert f.severity == "warn" and not f.dismissible
    f = next(
        x
        for x in checks.run_checks(session, today=due + timedelta(days=20))
        if x.kind == "invoice_overdue"
    )
    assert f.severity == "urgent"
    s = db.new_session()
    payments.record_payment(s, s.get(Invoice, inv.id))
    assert not {"invoice_overdue", "invoice_awaiting"} & kinds(s, today=due + timedelta(days=20))


def test_pension_form_b_by_payment_month_and_ten_week_rule(settings, session, ready):
    add(session, ready, date(2026, 8, 3))
    inv = session.get(Invoice, issue_month(settings, session, ready, "2026-08").id)
    found = {f.kind: f for f in checks.run_checks(session, today=TODAY)}
    # not paid yet: no Form B, but the 10-week limit (3 Aug + 70 days = 12 Oct) is close
    assert "pension_due" not in found and "pension_overdue" not in found
    tw = found["pension_deadline_unpaid"]
    assert tw.params["deadline"] == "2026-10-12" and tw.severity == "urgent"
    assert "pension_tier_missing" in found

    payments.record_payment(session, inv, paid_on=date(2026, 9, 10))
    found = {f.kind: f for f in checks.run_checks(session, today=date(2026, 10, 2))}
    # paid in September -> September's Form B, due by 7 October
    assert found["pension_due"].params == {
        "month": "2026-09",
        "pay": "540.00",
        "due": "2026-10-07",
        "days": 5,
    }
    assert "pension_deadline_form_a" in found  # paid, Form A not yet signed
    late = {f.kind: f for f in checks.run_checks(session, today=TODAY)}
    assert late["pension_overdue"].severity == "urgent"

    key = pension.month_figures(session, "2026-08")["forms_a"][0]["key"]
    pension.set_form_a(session, "2026-08", key, "signed")
    pension.mark_submitted(session, "2026-09")
    found = kinds(session)
    assert not {"pension_due", "pension_overdue"} & found
    assert not {k for k in found if k.startswith("pension_deadline")}
    s = db.new_session()
    payments.delete_payment(s, s.get(Invoice, inv.id).payments[0].id)
    assert "pension_changed" in kinds(s)  # September's received figures changed


def test_ten_week_rule_for_work_not_yet_invoiced(session, ready):
    add(session, ready, date(2026, 9, 1))
    found = {f.kind: f for f in checks.run_checks(session, today=date(2026, 10, 20))}
    f = found["pension_deadline_not_invoiced"]
    assert f.params["deadline"] == "2026-11-10" and f.severity == "warn"
    assert f.action == {"type": "create_invoice", "practice_id": ready.id, "month": "2026-09"}
    gone = kinds(session, today=date(2027, 3, 1))  # long past: nothing left to act on
    assert not {k for k in gone if k.startswith("pension_deadline")}


def test_po_required_finding_and_warning(session, ready):
    ready.po_required = True
    ready.invoice_instructions = "Email accounts@example.invalid with PO"
    session.commit()
    add(session, ready, date(2026, 9, 3))
    d = diary.invoice_month(session, ready.id, "2026-09")
    assert "po_missing" in kinds(session)
    a = svc.analyse(session, lines=d.lines, pension_enabled=True, practice=ready, reference=None)
    codes = [w.code for w in a.warnings]
    assert "invoice.po_required" in codes and "invoice.practice_instructions" in codes
    svc.save_draft(session, d, reference="PO-123")
    assert "po_missing" not in kinds(session)


def test_dismiss_hides_until_date(session, ready):
    add(session, ready, date(2026, 10, 1))
    key = next(
        f.key for f in checks.run_checks(session, today=TODAY) if f.kind == "uninvoiced_current"
    )
    checks.dismiss(session, key, days=3)
    real_today = core.today_london()
    assert "uninvoiced_current" not in kinds(session, today=real_today)
    assert "uninvoiced_current" in kinds(session, today=real_today + timedelta(days=4))


def test_backup_findings(settings, session, ready, tmp_path):
    add(session, ready, date(2026, 9, 3))
    issue_month(settings, session, ready, "2026-09")
    assert "backup_never" in kinds(session, settings)
    cli.backup(settings, tmp_path / "b.tar.gz")
    assert not {"backup_never", "backup_stale"} & kinds(
        session, settings, today=core.today_london()
    )
    later = core.today_london() + timedelta(days=10)
    assert "backup_stale" in kinds(session, settings, today=later)


class FakeSMTP:
    sent: list = []

    def __init__(self, cfg):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def send_message(self, msg, from_addr, to_addrs):
        FakeSMTP.sent.append((msg, to_addrs))


def test_digest_compose_send_and_schedule(settings, session, ready, monkeypatch):
    monkeypatch.setattr(mail, "resolve_and_check", lambda *a: None)
    box = SecretBox(settings)
    assert digest.compose(session, settings) is None  # nothing to report
    add(session, ready, date(2026, 9, 3), date(2026, 9, 4))
    subject, body = digest.compose(session, settings)
    assert "need attention" in subject
    assert (
        "September 2026 at Example Medical Practice is ready to invoice (2 sessions, £1,200.00)"
        in body
    )
    assert "00000000" not in body
    mail.save_config(
        session,
        box,
        {
            "enabled": True,
            "host": "smtp.example.invalid",
            "port": 587,
            "security": "starttls",
            "username": "u",
            "password": "pw",
            "from_address": "me@example.invalid",
        },
    )
    p = core.get_profile(session)
    monday_9 = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)  # 09:00 London (BST)
    assert digest.due(session, monday_9) is False  # opt-in
    p.digest_enabled = True
    session.commit()
    assert digest.due(session, monday_9) is True
    assert digest.due(session, datetime(2026, 10, 13, 8, 0, tzinfo=UTC)) is False  # Tuesday
    assert digest.due(session, datetime(2026, 10, 12, 5, 0, tzinfo=UTC)) is False  # 06:00
    FakeSMTP.sent.clear()
    assert digest.send_now(session, settings, box, smtp_factory=FakeSMTP)["sent"]
    msg, rcpts = FakeSMTP.sent[0]
    assert rcpts == ["me@example.invalid"]
    p.last_digest_sent_at = monday_9
    session.commit()
    assert digest.due(session, monday_9 + timedelta(hours=3)) is False  # once per week
    assert digest.due(session, monday_9 + timedelta(days=7)) is True


def test_self_assessment_figures(settings, session, ready):
    add(session, ready, date(2026, 9, 3))
    issue_month(settings, session, ready, "2026-09")
    p = core.get_profile(session)
    p.employee_rate = Decimal("0.098")
    session.commit()
    sa = reports.summary(session, 2026)["self_assessment"]
    assert sa == {
        "fees": "600.00",
        "employer_contributions": "77.65",
        "pensionable_pay": "540.00",
        "employee_rate": "0.098",
        "employee_contributions_estimate": "52.92",
    }


def test_checks_api(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert c.get("/api/v1/checks").json() == {
            "findings": [],
            "counts": {"urgent": 0, "warn": 0, "info": 0},
        }
        assert "findings" in c.get("/api/v1/overview").json()
        r = c.post("/api/v1/checks/dismiss?key=backup_never", json={"days": 3}, headers=h)
        assert r.json() == {"ok": True}
        r = c.post("/api/v1/digest/send", headers=h)
        assert r.json() == {"sent": False, "reason": "nothing_to_report"}
        r = c.patch("/api/v1/settings/profile", json={"digest_enabled": True}, headers=h)
        assert r.json()["digest_enabled"] is True
        r = c.post(
            "/api/v1/practices",
            json={
                "name": "Example Medical Practice",
                "po_required": True,
                "invoice_instructions": "Quote the PO",
            },
            headers=h,
        )
        assert r.json()["po_required"] is True


def test_automatic_backups(settings, session, ready, tmp_path):
    import os
    from dataclasses import replace

    from locuvi.errors import DomainError
    from locuvi.services import backups

    with __import__("pytest").raises(DomainError):
        backups.backup_now(settings)  # no BACKUP_DIR configured
    st = replace(settings, backup_dir=tmp_path / "backups", backup_keep_days=30)
    add(session, ready, date(2026, 9, 3))
    issue_month(st, session, ready, "2026-09")
    f = next(x for x in checks.run_checks(session, st) if x.kind == "backup_never")
    assert f.action == {"type": "backup_now"}
    night = datetime(2026, 10, 9, 2, 30, tzinfo=UTC)  # 03:30 London
    assert backups.nightly_due(st, night)
    assert not backups.nightly_due(st, datetime(2026, 10, 9, 0, 30, tzinfo=UTC))  # 01:30
    res = backups.backup_now(st)
    assert res["issued_invoices"] == 1 and (st.backup_dir / res["file"]).exists()
    assert not backups.nightly_due(st)  # done today
    old = st.backup_dir / "locuvi-2026-01-01-0200.tar.gz"
    old.write_bytes(b"x")
    os.utime(old, (0, 0))
    assert backups.prune(st) == 1 and not old.exists()
