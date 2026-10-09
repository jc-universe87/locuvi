"""Recently deleted: every delete → bin → restore (30 days), conflicts, purge."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_practice
from test_api import Api, client_for, setup_owner_and_practice

from locuvi import db
from locuvi.errors import Conflict, NotFound
from locuvi.models import (
    Invoice,
    InvoiceEvent,
    MailboxConfig,
    Payment,
    PensionSubmission,
    TrashItem,
    WorkSession,
    utcnow,
)
from locuvi.services import diary, documents, mailbox, payments, pension, trash
from locuvi.services import invoices as svc


def add(s, practice, *days, unit="am", **kw):
    return diary.add_sessions(s, [diary.SessionInput(practice.id, d, unit, **kw) for d in days])


def issue(settings, inv_id):
    return svc.issue(settings, inv_id, uuid.uuid4().hex).invoice


@pytest.fixture
def client(settings):
    with client_for(settings) as c:
        yield Api(c)


def only(s):
    items = trash.listing(s)
    assert len(items) == 1, items
    return items[0]


# ------------------------------------------------------------------ sessions


def test_session_delete_goes_to_bin_and_restores(session, ready):
    ws = add(session, ready, date(2026, 10, 13), rate=Decimal("612.50"))[0]
    sid = ws.id
    tid = diary.delete_session(session, ws)
    assert session.get(WorkSession, sid) is None
    item = only(session)
    assert item["id"] == tid and item["kind"] == "sessions"
    assert item["summary"] == {
        "count": 1,
        "practice": "Example Medical Practice",
        "date": "2026-10-13",
        "last_date": "2026-10-13",
        "unit": "am",
    }
    assert item["purge_on"] == (utcnow() + timedelta(days=30)).date().isoformat()
    # decimals stay decimal strings in the snapshot
    row = session.get(TrashItem, tid).payload_json["sessions"][0]
    assert row["rate"] == "612.50" and row["quantity"] == "1"

    out = trash.restore(session, tid)
    assert out["kind"] == "sessions" and out["restored"] == 1
    back = session.get(WorkSession, sid)
    assert back.rate == Decimal("612.50") and back.date == date(2026, 10, 13)
    assert trash.listing(session) == []
    with pytest.raises(NotFound):
        trash.restore(session, tid)


def test_series_undo_is_one_bin_entry(session, ready):
    ids = [w.id for w in add(session, ready, date(2026, 10, 7), date(2026, 10, 14))]
    assert diary.delete_many(session, ids) == 2
    item = only(session)
    assert item["summary"]["count"] == 2 and item["summary"]["last_date"] == "2026-10-14"
    assert trash.restore(session, item["id"])["restored"] == 2
    assert session.query(WorkSession).count() == 2


def test_session_restore_clash_and_partial(session, ready):
    a, b = add(session, ready, date(2026, 10, 7), date(2026, 10, 14))
    diary.delete_many(session, [a.id, b.id])
    tid = only(session)["id"]
    add(session, ready, date(2026, 10, 7))  # booked again meanwhile
    out = trash.restore(session, tid)
    assert out["restored"] == 1 and out["skipped"] == 1
    # a single clashing session fails with a clear reason and stays in the bin
    c = add(session, ready, date(2026, 10, 21))[0]
    tid = diary.delete_session(session, c)
    add(session, ready, date(2026, 10, 21))
    with pytest.raises(Conflict) as e:
        trash.restore(session, tid)
    assert e.value.code == "trash.session_clash"
    assert e.value.params["practice"] == "Example Medical Practice"
    session.rollback()
    assert only(session)["id"] == tid


def test_session_restore_needs_its_practice(session, ready):
    other = make_practice(session, name="Second Example Surgery")
    tid = diary.delete_session(session, add(session, other, date(2026, 10, 9))[0])
    # practices are never deleted in the app; simulate one missing from an old snapshot
    item = session.get(TrashItem, tid)
    rows = [dict(r, practice_id="missing") for r in item.payload_json["sessions"]]
    item.payload_json = {"sessions": rows}
    session.commit()
    with pytest.raises(Conflict) as e:
        trash.restore(session, tid)
    assert e.value.code == "trash.practice_gone"


def test_issued_session_still_cannot_be_deleted(settings, session, ready):
    add(session, ready, date(2026, 9, 1))
    issue(settings, diary.invoice_month(session, ready.id, "2026-09").id)
    s = db.new_session()
    ws = s.query(WorkSession).one()
    with pytest.raises(Conflict):
        diary.delete_session(s, ws)
    assert trash.listing(s) == []


# ------------------------------------------------------------------ drafts


def test_draft_delete_and_restore_relinks_unbilled_sessions(session, ready):
    add(session, ready, date(2026, 10, 1), date(2026, 10, 2))
    d = diary.invoice_month(session, ready.id, "2026-10")
    inv_id, total = d.id, d.grand_total
    tid = svc.delete_draft(session, d)
    assert session.get(Invoice, inv_id) is None
    assert diary.ready_to_invoice(session)[0]["sessions"] == 2
    item = only(session)
    assert item["kind"] == "invoice" and item["summary"]["lines"] == 2
    assert item["summary"]["total"] == str(total)

    # one session is billed elsewhere meanwhile: only the other comes back onto the draft
    ws = session.query(WorkSession).order_by(WorkSession.date).all()
    other = Invoice(status="draft")
    session.add(other)
    session.flush()
    ws[0].invoice_id = other.id
    session.commit()

    out = trash.restore(session, tid)
    assert out["id"] == inv_id and out["sessions_linked"] == 1 and out["sessions_skipped"] == 1
    back = session.get(Invoice, inv_id)
    assert back.status == "draft" and back.invoice_number is None
    assert back.grand_total == total and len(back.lines) == 2
    assert back.lines[0].quantity == Decimal("1")
    types = [e.event_type for e in session.query(InvoiceEvent).filter_by(invoice_id=inv_id)]
    assert "restored" in types
    assert ws[1].invoice_id == inv_id


def test_issued_invoice_cannot_be_deleted(settings, session, ready):
    add(session, ready, date(2026, 9, 1))
    inv = issue(settings, diary.invoice_month(session, ready.id, "2026-09").id)
    s = db.new_session()
    with pytest.raises(Conflict) as e:
        svc.delete_draft(s, s.get(Invoice, inv.id))
    assert e.value.code == "invoice.not_draft"
    s.rollback()
    assert trash.listing(s) == [] and s.get(Invoice, inv.id).status == "issued"


# ------------------------------------------------------------------ payments


def _issued(settings, session, ready, d=date(2026, 9, 1)):
    add(session, ready, d)
    inv = issue(settings, diary.invoice_month(session, ready.id, f"{d:%Y-%m}").id)
    s = db.new_session()
    return s, s.get(Invoice, inv.id)


def test_payment_delete_and_restore(settings, session, ready):
    s, inv = _issued(settings, session, ready)
    p = payments.record_payment(s, inv, amount=Decimal("100.00"))
    pid = p.id
    _, tid = payments.delete_payment(s, pid)
    assert s.get(Payment, pid) is None
    item = only(s)
    assert item["kind"] == "payment" and item["summary"]["amount"] == "100.00"
    assert item["summary"]["invoice_number"] == inv.invoice_number
    trash.restore(s, tid)
    assert s.get(Payment, pid).amount == Decimal("100.00")
    assert payments.payment_state(inv)["paid"] == "100.00"


def test_payment_restore_would_overpay(settings, session, ready):
    s, inv = _issued(settings, session, ready)
    p = payments.record_payment(s, inv)  # paid in full
    _, tid = payments.delete_payment(s, p.id)
    payments.record_payment(s, inv)  # marked paid again
    with pytest.raises(Conflict) as e:
        trash.restore(s, tid)
    assert e.value.code == "trash.payment_too_much"


def test_bank_undo_does_not_fill_the_bin(settings, session, ready):
    s, inv = _issued(settings, session, ready)
    p = payments.record_payment(s, inv)
    payments.delete_payment(s, p.id, keep_copy=False)
    assert trash.listing(s) == []


# ------------------------------------------------------------------ pension


def test_policy_delete_and_restore(client):
    api = client
    r = api.post(
        "/api/v1/settings/pension-policies",
        {"effective_from": "2027-04-01", "employer_rate": "0.15"},
    )
    pid = r.json()["id"]
    r = api.c.delete(f"/api/v1/settings/pension-policies/{pid}", headers=api.h())
    assert r.status_code == 200
    tid = r.json()["trash_id"]
    items = api.get("/api/v1/trash").json()["items"]
    assert items[0]["kind"] == "pension_policy"
    assert items[0]["summary"]["employer_rate"] == "0.15"
    # another rate from the same day meanwhile: restore refuses
    r2 = api.post(
        "/api/v1/settings/pension-policies",
        {"effective_from": "2027-04-01", "employer_rate": "0.16"},
    )
    assert r2.status_code == 201
    r = api.post(f"/api/v1/trash/{tid}/restore")
    assert r.status_code == 409 and r.json()["error"]["code"] == "trash.policy_exists"
    api.c.delete(f"/api/v1/settings/pension-policies/{r2.json()['id']}", headers=api.h())
    r = api.post(f"/api/v1/trash/{tid}/restore")
    assert r.status_code == 200, r.text
    rates = {p["employer_rate"] for p in api.get("/api/v1/settings/pension-policies").json()}
    assert "0.15" in rates and "0.16" not in rates


def test_unmark_submitted_goes_to_bin(settings, session, ready):
    s, inv = _issued(settings, session, ready, date(2026, 9, 3))
    payments.record_payment(s, inv, paid_on=date(2026, 9, 28))
    pension.mark_submitted(s, "2026-09", date(2026, 10, 2))
    tid = pension.unmark_submitted(s, "2026-09")
    assert s.query(PensionSubmission).count() == 0
    assert only(s)["summary"] == {"month": "2026-09", "submitted_on": "2026-10-02"}
    trash.restore(s, tid)
    sub = s.query(PensionSubmission).one()
    assert sub.submitted_on == date(2026, 10, 2) and sub.figures_json["form_b"]["items"]
    # marked again after unmarking: the old record can't come back on top
    tid = pension.unmark_submitted(s, "2026-09")
    pension.mark_submitted(s, "2026-09")
    with pytest.raises(Conflict) as e:
        trash.restore(s, tid)
    assert e.value.code == "trash.month_submitted"


# ------------------------------------------------------- documents and mail


def test_documents_and_mail_accounts_show_in_bin(session):
    doc = documents.add_paste(session, "Locum cover at Example Surgery", "booking")
    documents.trash(session, doc)
    acc = MailboxConfig(label="work@example.invalid", username="work@example.invalid")
    session.add(acc)
    session.commit()
    mailbox.remove_account(session, acc.id)
    items = trash.listing(session)
    assert [i["kind"] for i in items] == ["mailbox", "document"]  # newest first
    assert items[0]["label"] == "work@example.invalid"
    trash.restore(session, f"document:{doc.id}")
    trash.restore(session, f"mailbox:{acc.id}")
    assert trash.listing(session) == []
    assert documents.get(session, doc.id).deleted_at is None
    assert [a.id for a in mailbox.list_accounts(session)] == [acc.id]
    with pytest.raises(NotFound):
        trash.restore(session, f"mailbox:{acc.id}")
    with pytest.raises(NotFound):
        trash.restore(session, f"document:{doc.id}")


# ------------------------------------------------------------------ purge


def test_purge_after_30_days(session, ready):
    tid = diary.delete_session(session, add(session, ready, date(2026, 10, 13))[0])
    assert trash.purge(session) == 0
    assert trash.purge(session, now=utcnow() + timedelta(days=29)) == 0
    assert trash.purge(session, now=utcnow() + timedelta(days=31)) == 1
    assert session.get(TrashItem, tid) is None
    with pytest.raises(NotFound):
        trash.restore(session, tid)


def test_scheduler_purges_the_bin(settings, session, ready):
    from locuvi.secrets_store import SecretBox
    from locuvi.services.digest import DigestScheduler

    tid = diary.delete_session(session, add(session, ready, date(2026, 10, 13))[0])
    item = session.get(TrashItem, tid)
    item.deleted_at = utcnow() - timedelta(days=31)
    session.commit()
    DigestScheduler(settings, SecretBox(settings)).tick()
    session.expire_all()
    assert session.get(TrashItem, tid) is None


# ------------------------------------------------------------------ API


def test_api_delete_restore_round_trip(client):
    api = client
    pid = setup_owner_and_practice(api)
    r = api.post(
        "/api/v1/sessions",
        {"sessions": [{"practice_id": pid, "date": "2026-10-13", "unit": "am", "rate": "600.00"}]},
    )
    sid = r.json()[0]["id"]
    r = api.c.delete(f"/api/v1/sessions/{sid}", headers=api.h())
    assert r.status_code == 200
    tid = r.json()["trash_id"]
    body = api.get("/api/v1/trash").json()
    assert body["keep_days"] == 30 and body["items"][0]["id"] == tid
    r = api.post(f"/api/v1/trash/{tid}/restore")
    assert r.status_code == 200 and r.json()["restored"] == 1
    assert api.get("/api/v1/trash").json()["items"] == []
    assert api.post(f"/api/v1/trash/{tid}/restore").status_code == 404
    assert api.post("/api/v1/trash/mailbox:999/restore").status_code == 404
    assert api.post("/api/v1/trash/document:nope/restore").status_code == 404

    # drafts: deleted to the bin; restore brings back the same draft
    r = api.post("/api/v1/invoices", {"practice_id": pid, "lines": []})
    assert r.status_code == 201, r.text
    inv_id = r.json()["id"]
    r = api.c.delete(f"/api/v1/invoices/{inv_id}", headers=api.h())
    assert r.status_code == 200
    assert api.get(f"/api/v1/invoices/{inv_id}").status_code == 404
    api.post(f"/api/v1/trash/{r.json()['trash_id']}/restore")
    assert api.get(f"/api/v1/invoices/{inv_id}").json()["status"] == "draft"
