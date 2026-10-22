"""Email reminders before NHS pension deadlines. Fictional data only."""

from __future__ import annotations

from datetime import UTC, date, datetime

from test_checks import FakeSMTP, add, issue_month

from locuvi import mail
from locuvi.models import Invoice
from locuvi.secrets_store import SecretBox
from locuvi.services import core, payments, pension, pension_reminders


def _email_on(session, box):
    mail.save_config(session, box, {
        "enabled": True, "host": "smtp.example.invalid", "port": 587, "security": "starttls",
        "username": "u", "password": "pw", "from_address": "me@example.invalid",
    })  # fmt: skip


def at(d: date, hour_utc: int = 8) -> datetime:
    return datetime(d.year, d.month, d.day, hour_utc, 0, tzinfo=UTC)  # 09:00 London in BST


def send(session, settings, box, when):
    FakeSMTP.sent.clear()
    return pension_reminders.send_if_due(session, settings, box, FakeSMTP, now=when)


def test_reminders_are_opt_in_once_per_stage_and_stop_when_done(
    settings, session, ready, monkeypatch
):
    monkeypatch.setattr(mail, "resolve_and_check", lambda *a: None)
    box = SecretBox(settings)
    add(session, ready, date(2026, 8, 3))
    inv = session.get(Invoice, issue_month(settings, session, ready, "2026-08").id)
    payments.record_payment(session, inv, paid_on=date(2026, 9, 10))  # September's Form B

    # off by default, and never without email set up
    assert send(session, settings, box, at(date(2026, 10, 2)))["sent"] is False
    core.get_profile(session).pension_reminders = True
    session.commit()
    assert send(session, settings, box, at(date(2026, 10, 2)))["reason"] == "off_or_too_early"
    _email_on(session, box)
    assert send(session, settings, box, at(date(2026, 10, 2), 5))["sent"] is False  # 06:00

    # 2 Oct: Form B due 7 Oct (5 days) and the 10-week limit (12 Oct) both close
    r = send(session, settings, box, at(date(2026, 10, 2)))
    assert r["sent"] and r["count"] == 2
    msg, rcpts = FakeSMTP.sent[0]
    body = msg.get_content()
    assert rcpts == ["me@example.invalid"] and "coming up" in msg["Subject"]
    assert "Form B for fees received in September 2026" in body and "7 Oct 2026" in body
    assert "Form A for work ending 3 Aug 2026 isn't signed; due by 12 Oct 2026" in body
    assert "pcse.england.nhs.uk" in body and "doesn't submit anything" in body

    # the same reminders aren't sent again the next hour or day
    assert send(session, settings, box, at(date(2026, 10, 3)))["reason"] == "nothing_new"
    # 8 Oct: Form B is now late, which is a new stage
    r = send(session, settings, box, at(date(2026, 10, 8)))
    assert r["count"] == 1 and "has passed" in FakeSMTP.sent[0][0]["Subject"]
    assert "Still to do from earlier reminders" in FakeSMTP.sent[0][0].get_content()

    # once the forms are recorded as done, nothing more is due
    key = pension.month_figures(session, "2026-08")["forms_a"][0]["key"]
    pension.set_form_a(session, "2026-08", key, "signed")
    pension.mark_submitted(session, "2026-09")
    assert send(session, settings, box, at(date(2026, 10, 9)))["reason"] == "nothing_new"
    assert pension_reminders.due_items(session, settings, date(2026, 10, 9)) == []


def test_profile_setting_round_trips(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert c.get("/api/v1/settings/profile").json()["pension_reminders"] is False
        r = c.patch("/api/v1/settings/profile", headers=h, json={"pension_reminders": True})
        assert r.json()["pension_reminders"] is True
