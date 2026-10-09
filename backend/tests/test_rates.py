"""Session vs hourly rates, and rates agreed including the employer pension. Fictional data."""

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from locuvi.money import PensionPolicyValues, basic_from_inclusive
from locuvi.services import diary
from locuvi.services import invoices as svc

D = Decimal
POLICY = PensionPolicyValues(date(2026, 4, 1), D("0.90"), D("0.1438"))


@pytest.mark.parametrize(
    ("agreed", "basic"),
    [("600.00", "531.25"), ("500.00", "442.71"), ("95.00", "84.11"), ("0.00", "0.00")],
)
def test_basic_from_inclusive(agreed, basic):
    # agreed ÷ (1 + 0.90 × 0.1438) = agreed ÷ 1.12942, half-up to the penny
    assert basic_from_inclusive(D(agreed), POLICY) == D(basic)


def inclusive(session, ready):
    ready.rate_includes_pension = True
    session.commit()
    return ready


def test_inclusive_sessions_become_basic_fee_plus_pension(settings, session, ready):
    p = inclusive(session, ready)
    diary.add_sessions(session, [diary.SessionInput(p.id, date(2026, 9, d)) for d in (1, 2, 3)])
    draft = diary.invoice_month(session, p.id, "2026-09")
    assert [(ln.agreed_rate, ln.unit_price) for ln in draft.lines] == [
        (D("600.00"), D("531.25"))
    ] * 3
    # 3 × 531.25 = 1593.75 basic; 90% = 1434.38; 14.38% = 206.26; total 1800.01
    assert (draft.pensionable_basic_total, draft.pensionable_pay) == (D("1593.75"), D("1434.38"))
    assert (draft.employer_contribution, draft.grand_total) == (D("206.26"), D("1800.01"))
    a = svc.analyse(session, lines=draft.lines, pension_enabled=True, practice=p)
    rounding = [w for w in a.warnings if w.code == "invoice.inclusive_rounding"]
    assert rounding[0].params == {"agreed": "1800.00", "total": "1800.01", "difference": "0.01"}
    assert not [w for w in a.warnings if w.code == "invoice.practice_rate_inclusive"]

    inv = svc.issue(settings, draft.id, uuid.uuid4().hex).invoice
    snap = inv.immutable_snapshot_json
    assert (
        snap["lines"][0]["agreed_rate"] == "600.00" and snap["lines"][0]["unit_price"] == "531.25"
    )
    text = PdfReader(io.BytesIO((settings.data_dir / inv.local_pdf_path).read_bytes())).pages[0]
    note = " ".join(text.extract_text().split())
    assert "Agreed £600.00 per session, including the employer NHS pension contribution" in note
    assert "÷ 1.12942" in note


def test_inclusive_rate_without_pension_is_charged_as_agreed(session, ready):
    p = inclusive(session, ready)
    diary.add_sessions(
        session,
        [diary.SessionInput(p.id, date(2026, 9, 1)),
         diary.SessionInput(p.id, date(2026, 9, 2), pensionable=False)],
    )  # fmt: skip
    draft = diary.invoice_month(session, p.id, "2026-09")
    assert [ln.unit_price for ln in draft.lines] == [D("531.25"), D("600.00")]
    # switching pension off for the whole invoice charges every line at the agreed figure
    draft = svc.save_draft(session, draft, pension_enabled=False)
    assert [ln.unit_price for ln in draft.lines] == [D("600.00"), D("600.00")]
    assert draft.grand_total == D("1200.00") and draft.employer_contribution == D("0")
    draft = svc.save_draft(session, draft, pension_enabled=True)
    assert draft.lines[0].unit_price == D("531.25")


def test_exclusive_practice_unchanged(session, ready):
    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 1))])
    draft = diary.invoice_month(session, ready.id, "2026-09")
    ln = draft.lines[0]
    assert ln.agreed_rate is None and ln.unit_price == D("600.00")
    assert draft.grand_total == D("677.65")  # 600 + 14.38% of 540


def test_split_and_duplicate_keep_agreed_rate(session, ready):
    p = inclusive(session, ready)
    diary.add_sessions(session, [diary.SessionInput(p.id, date(2026, 9, 1))])
    draft = diary.invoice_month(session, p.id, "2026-09")
    copy = svc.duplicate(session, draft)
    assert copy.lines[0].agreed_rate == D("600.00") and copy.lines[0].unit_price == D("531.25")


def test_hourly_practice_defaults(session, ready):
    ready.default_unit, ready.hourly_rate, ready.default_hours = "hours", D("95.00"), D("4.5")
    session.commit()
    (ws,) = diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 1), "hours")])
    assert (ws.rate, ws.quantity) == (D("95.00"), D("4.5"))
    # the session rate is never used as an hourly rate
    ready.hourly_rate = None
    session.commit()
    session.query(type(ws)).delete()
    session.commit()
    with pytest.raises(Exception, match="Enter a rate"):
        diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 2), "hours")])


def test_hourly_inclusive(session, ready):
    ready.rate_includes_pension = True
    ready.default_unit, ready.hourly_rate, ready.default_hours = "hours", D("95.00"), D("4")
    session.commit()
    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 1), "hours")])
    draft = diary.invoice_month(session, ready.id, "2026-09")
    ln = draft.lines[0]
    assert (ln.quantity, ln.agreed_rate, ln.unit_price, ln.amount) == (
        D("4"), D("95.00"), D("84.11"), D("336.44"))  # fmt: skip


def test_api_practice_rates_and_line_agreed_rate(settings, session, ready):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        r = c.post("/api/v1/practices", headers=h, json={
            "name": "Example Hourly Surgery", "default_unit": "hours", "hourly_rate": "95.00",
            "default_hours": "4", "rate_includes_pension": True})  # fmt: skip
        assert r.status_code == 201, r.text
        pr = r.json()
        assert (pr["hourly_rate"], pr["default_hours"], pr["default_unit"]) == (
            "95.00",
            "4",
            "hours",
        )
        bad = c.patch(f"/api/v1/practices/{pr['id']}", headers=h, json={"default_hours": "30"})
        assert bad.status_code == 400
        sug = c.get(f"/api/v1/sessions/suggest-rate?practice_id={pr['id']}&unit=hours").json()
        assert sug == {"rate": "95.00", "pensionable": True, "includes_pension": True, "hours": "4"}

        inv = c.post("/api/v1/invoices", headers=h, json={
            "practice_id": pr["id"],
            "lines": [{"service_date": "2026-09-01", "unit": "hours", "quantity": "4",
                       "unit_price": "0", "agreed_rate": "95.00", "pensionable": True}],
        }).json()  # fmt: skip
        line = inv["lines"][0]
        assert (line["agreed_rate"], line["unit_price"]) == ("95.00", "84.11")
