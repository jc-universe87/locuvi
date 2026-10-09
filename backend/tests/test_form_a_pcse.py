"""Form A tracking and PCSE comparison. Fictional data only."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_practice

from locuvi.errors import DomainError
from locuvi.services import checks, core, diary, pension
from locuvi.services import invoices as svc


def issue(settings, s, practice, month, days):
    diary.add_sessions(
        s, [diary.SessionInput(practice.id, date.fromisoformat(f"{month}-{d:02d}")) for d in days]
    )
    d = diary.invoice_month(s, practice.id, month)
    svc.issue(settings, d.id, uuid.uuid4().hex)
    s.expire_all()


def test_form_a_progress_and_chase(settings, session, ready):
    other = make_practice(session, name="Riverside Surgery")
    issue(settings, session, ready, "2026-08", [3])
    issue(settings, session, other, "2026-08", [5])
    fig = pension.month_figures(session, "2026-08")
    keys = {a["practice_name"]: a["key"] for a in fig["forms_a"]}
    assert all(a["form_a"]["status"] == "to_send" for a in fig["forms_a"])

    long_ago = core.today_london() - timedelta(days=20)
    pension.set_form_a(session, "2026-08", keys[ready.name], "sent", long_ago)
    pension.set_form_a(session, "2026-08", keys[other.name], "signed")
    fig = pension.month_figures(session, "2026-08")
    st = {a["practice_name"]: a["form_a"] for a in fig["forms_a"]}
    assert st[ready.name]["status"] == "sent" and st[ready.name]["sent_on"] == long_ago.isoformat()
    assert st[other.name]["status"] == "signed" and st[other.name]["signed_on"]

    row = pension.overview(session)[0]
    assert row["forms_a_signed"] == 1 and row["practices"] == 2
    found = [f for f in checks.run_checks(session) if f.kind == "form_a_chase"]
    assert len(found) == 1 and found[0].params["practice"] == ready.name

    pension.set_form_a(session, "2026-08", keys[ready.name], "signed")
    assert not [f for f in checks.run_checks(session) if f.kind == "form_a_chase"]
    pension.set_form_a(session, "2026-08", keys[ready.name], "to_send")
    fig = pension.month_figures(session, "2026-08")
    assert {a["form_a"]["status"] for a in fig["forms_a"]} == {"to_send", "signed"}

    with pytest.raises(DomainError):
        pension.set_form_a(session, "2026-08", "not-a-practice", "sent")
    with pytest.raises(DomainError):
        pension.set_form_a(session, "2026-08", keys[ready.name], "lost")


def test_form_a_progress_does_not_count_as_figure_change(settings, session, ready):
    issue(settings, session, ready, "2026-08", [3])
    pension.mark_submitted(session, "2026-08")
    key = pension.month_figures(session, "2026-08")["forms_a"][0]["key"]
    pension.set_form_a(session, "2026-08", key, "signed")
    assert pension.overview(session)[0]["changed_since_submitted"] is False


def test_pcse_manual_and_csv(settings, session, ready):
    core.get_profile(session).employee_rate = Decimal("0.098")
    session.commit()
    issue(settings, session, ready, "2026-08", [3])  # pay 540.00, employer 77.65
    issue(settings, session, ready, "2026-09", [3])
    fig = pension.month_figures(session, "2026-08")
    assert fig["pcse"]["status"] == "none"
    expected = Decimal(fig["form_b"]["total_payable"])

    pension.set_pcse(session, "2026-08", Decimal("540.00"), expected)
    assert pension.month_figures(session, "2026-08")["pcse"]["status"] == "match"

    csv_text = (
        "Month,Practice,Pensionable pay,Contributions\n"
        "Sep 2026,Example Medical Practice,300.00,\n"
        "Sep 2026,Example Medical Practice,200.00,\n"
        "2026-08,Example Medical Practice,540.00,\n"
    )
    assert pension.import_pcse(session, csv_text.encode())["months"] == 2
    sep = pension.month_figures(session, "2026-09")["pcse"]
    assert sep["recorded_pay"] == "500.00" and sep["status"] == "mismatch"
    assert sep["difference"] == "-40.00"
    found = {f.kind: f for f in checks.run_checks(session)}
    assert found["pcse_mismatch"].params["month"] == "2026-09"
    aug = pension.month_figures(session, "2026-08")["pcse"]
    assert aug["status"] == "match"  # CSV replaced the manual row with pay only

    pension.set_pcse(session, "2026-09", None, None)
    assert pension.month_figures(session, "2026-09")["pcse"]["status"] == "none"
    with pytest.raises(DomainError):
        pension.import_pcse(session, b"Foo,Bar\n1,2\n")
    with pytest.raises(DomainError):
        pension.set_pcse(session, "2026-09", Decimal("1.234"), None)


def test_api_form_a_and_pcse(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        r = c.post(
            "/api/v1/pension/2026-08/form-a",
            headers=h,
            json={"practice_key": "x", "status": "sent"},
        )
        assert r.status_code == 400  # no pensionable work that month
        r = c.put("/api/v1/pension/2026-08/pcse", headers=h, json={"pensionable_pay": "540.00"})
        assert r.status_code == 200 and r.json()["pcse"]["recorded_pay"] == "540.00"
        r = c.post(
            "/api/v1/pension/pcse/import",
            headers=h,
            files={"file": ("p.csv", b"Month,Pensionable pay\n2026-07,100.00\n", "text/csv")},
        )
        assert r.status_code == 200 and r.json()["imported"] == 1
