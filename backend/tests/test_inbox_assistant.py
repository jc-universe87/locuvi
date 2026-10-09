"""Document inbox, booking reader (rules + AI provider) and proposals. Fictional data only.

No test calls a real AI service: the provider is faked or given a fake SDK client.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import make_practice

from locuvi.assistant import providers, rules
from locuvi.errors import Conflict, DomainError
from locuvi.models import AuditEvent, Document, Proposal, SessionStatus, WorkSession
from locuvi.secrets_store import SecretBox
from locuvi.services import checks, diary, documents, proposals

TODAY = date(2026, 10, 8)

BOOKING = """Subject: Locum sessions confirmed
Hi Dr Example,
Thank you for covering at Example Medical Practice:
Monday 12th October AM
Tuesday 13 Oct 14:00-18:00
Thu 15/10/2026 full day
Fee £600 per session.
Cancelled: Friday 16th October PM
> On 1 Oct someone wrote: 3rd Nov am
Kind regards, Practice Manager
"""


# ------------------------------------------------------------------ rules


def test_rules_reads_common_booking_shapes():
    out = rules.extract(BOOKING, TODAY)
    got = [(i["date"], i["unit"], i["rate"], i["action"]) for i in out["items"]]
    assert got == [
        ("2026-10-12", "am", "600.00", "add"),
        ("2026-10-13", "pm", "600.00", "add"),
        ("2026-10-15", "day", "600.00", "add"),
        ("2026-10-16", "pm", "600.00", "cancel"),
    ]  # quoted reply ignored


def test_rules_year_inference_and_hours():
    # 5 Jan without a year, seen in October: the nearest one is next January
    assert rules.find_dates("5th January", TODAY)[0][1] == date(2027, 1, 5)
    assert rules.find_dates("on 03/04/26", TODAY)[0][1] == date(2026, 4, 3)  # day-first
    out = rules.extract("Hourly cover 21 October 09:00-13:30 at £95 per hour", TODAY)
    (item,) = out["items"]
    assert (item["unit"], item["hours"], item["rate"]) == ("hours", "4.50", "95.00")


def test_rules_am_pm_wording():
    def units(text):
        return [i["unit"] for i in rules.extract(text, TODAY)["items"]]

    assert units("I am pleased to confirm 12 Oct, 2-6pm") == ["pm"]  # "I am" is not AM
    assert units("12 Oct 2-6") == ["pm"]
    assert units("12 Oct 9-1") == ["am"]
    assert units("12 Oct 08:30-18:30") == ["day"]
    assert units("Monday 12th October am session") == ["am"]
    assert units("15 Oct AM & PM") == ["day"]


def test_rules_no_dates_asks_question():
    out = rules.extract("Thanks for your help last week!", TODAY)
    assert out["items"] == [] and out["questions"]


# -------------------------------------------------------------- documents


def test_upload_paste_dedupe_and_trash(settings, session, ready):
    doc = documents.add_upload(
        session, settings, "../../etc/booking.txt", "text/plain", BOOKING.encode()
    )
    assert doc.filename == "booking.txt"  # path stripped
    assert doc.kind == "booking" and doc.practice_id == ready.id
    assert doc.title == "booking.txt"
    stored = documents.file_path(settings, doc)
    assert stored is not None and stored.parent == settings.data_dir / "documents"
    assert stored.name != "booking.txt"  # random stored name
    again = documents.add_upload(session, settings, "copy.txt", "text/plain", BOOKING.encode())
    assert again.id == doc.id  # same bytes, same document

    with pytest.raises(DomainError):
        documents.add_upload(session, settings, "x.exe", "application/octet-stream", b"MZ...")
    with pytest.raises(DomainError):  # claims to be a PDF but isn't
        documents.add_upload(session, settings, "x.pdf", "application/pdf", b"hello")

    pasted = documents.add_paste(session, "Remittance advice: BACS payment £1,200")
    assert pasted.kind == "remittance" and pasted.source == "paste"
    assert documents.new_count(session) == 2

    documents.trash(session, doc)
    assert [d.id for d in documents.list_docs(session)] == [pasted.id]
    documents.restore(session, documents.get(session, doc.id, include_deleted=True))
    documents.trash(session, doc)
    doc.deleted_at = datetime.now(UTC) - timedelta(days=31)
    session.commit()
    assert documents.purge_trash(session, settings) == 1
    assert not stored.exists()


def test_pdf_and_email_text_extraction(settings, session):
    import io
    from email.message import EmailMessage

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Locum booking 12 October AM")
    c.save()
    doc = documents.add_upload(session, settings, "b.pdf", "application/pdf", buf.getvalue())
    assert "12 October" in doc.text_content and doc.content_type == "application/pdf"

    msg = EmailMessage()
    msg["From"] = "manager@example.invalid"
    msg["Subject"] = "Sessions next week"
    msg.set_content("Please cover Tuesday 13 Oct PM.")
    doc = documents.add_upload(session, settings, "m.eml", None, msg.as_bytes())
    assert doc.title == "Sessions next week" and "13 Oct PM" in doc.text_content


# -------------------------------------------------------------- proposals


def _propose(session, text=BOOKING):
    doc = documents.add_paste(session, text, "booking")
    return proposals.build(
        session, rules.extract(text, TODAY), engine="rules", document=doc, today=TODAY
    ), doc


def test_proposal_flags_and_accept(session, ready):
    other = make_practice(session, name="Second Example Surgery")
    diary.add_sessions(
        session,
        [
            diary.SessionInput(ready.id, date(2026, 10, 12), "am"),  # duplicate of item 0
            diary.SessionInput(other.id, date(2026, 10, 15), "pm"),  # clashes with full day
            diary.SessionInput(ready.id, date(2026, 10, 16), "pm"),  # to be cancelled
        ],
    )
    prop, doc = _propose(session)
    items = prop.payload_json["items"]
    assert items[0]["flags"] == ["duplicate"] and items[0]["selected"] is False
    assert items[1]["flags"] == [] and items[1]["selected"] is True
    assert items[2]["flags"] == ["clash"] and items[2]["clash_with"] == other.name
    assert items[3]["action"] == "cancel" and items[3]["session_id"]
    assert all(i["practice_id"] == ready.id for i in items)  # from the document

    # owner changes the rate on one item; server re-validates
    proposals.accept(session, prop, [{"index": 1, "rate": "650.00"}, {"index": 3}], today=TODAY)
    assert prop.status == "partial" and doc.status == "done"
    new = session.get(WorkSession, prop.result_json["created"][0])
    assert (new.date, new.unit, new.rate) == (date(2026, 10, 13), "pm", Decimal("650.00"))
    cancelled = session.get(WorkSession, prop.result_json["cancelled"][0])
    assert cancelled.status == SessionStatus.cancelled
    with pytest.raises(Conflict):
        proposals.accept(session, prop, [{"index": 2}], today=TODAY)

    proposals.undo(session, prop)
    assert prop.status == "pending" and session.get(WorkSession, new.id) is None
    assert session.get(WorkSession, cancelled.id).status == SessionStatus.active
    events = [e.event_type for e in session.query(AuditEvent).all()]
    assert {"proposal.created", "proposal.accepted", "proposal.undone"} <= set(events)

    proposals.reject(session, prop)
    assert prop.status == "rejected"


def test_proposal_needs_practice_and_rate(session, ready):
    unknown = "Please cover 20 October AM and 21 October PM."
    prop, _ = _propose(session, unknown)
    a, b = prop.payload_json["items"]
    assert "needs_practice" in a["flags"] and a["selected"] is False
    with pytest.raises(DomainError):
        proposals.accept(session, prop, [{"index": 0}], today=TODAY)
    # owner picks the practice; remembered rate fills in
    proposals.accept(session, prop, [{"index": 0, "practice_id": ready.id}], today=TODAY)
    w = session.get(WorkSession, prop.result_json["created"][0])
    assert w.rate == Decimal("600.00") and w.practice_id == ready.id


def test_bad_values_from_engine_are_dropped_or_cleaned(session, ready):
    raw = {
        "summary": "x" * 2000,
        "items": [
            {"date": "not-a-date", "unit": "am"},
            {"date": "1999-01-01", "unit": "am"},  # absurdly far away
            {
                "date": "2026-10-20",
                "unit": "weekend",
                "rate": "-5",
                "practice_id": "nope",
                "practice_name": ready.name.upper(),
                "action": "delete-all",
            },
            {"date": "2026-10-21", "unit": "hours", "hours": "1e9", "rate": "£1,234.567"},
        ],
        "questions": ["", "Is the fee per session?"],
    }
    prop = proposals.build(session, raw, engine="ai:test", today=TODAY)
    items = prop.payload_json["items"]
    assert len(items) == 2 and len(prop.payload_json["summary"]) == 500
    assert items[0]["unit"] == "day" and items[0]["action"] == "add"
    assert items[0]["practice_id"] == ready.id  # matched by name
    assert items[0]["rate_source"] == "remembered"  # negative rate rejected
    assert items[1]["unit"] == "day"  # bad hours -> not hourly
    assert items[1]["rate"] == "1234.57"
    assert prop.payload_json["questions"] == ["Is the fee per session?"]


# ---------------------------------------------------------------- AI provider


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn", model="claude-opus-5-5"):
        self.payload, self.stop_reason, self.model = payload, stop_reason, model
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.payload)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model=self.model,
            content=[SimpleNamespace(type="text", text=text)],
        )


def fake_client(msgs):
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs))


def test_anthropic_provider_request_shape_and_minimisation():
    msgs = FakeMessages({"summary": "s", "items": [], "questions": []})
    p = providers.AnthropicProvider("sk-test", "claude-opus-5-5", client=fake_client(msgs))
    text = "Cover 12 Oct AM. Patient NHS no 943 476 5919, DOB: 01/02/1960. Acct 12345678."
    out = p.read_booking(
        text=text,
        attachment=None,
        today=TODAY,
        practices=[{"id": "p1", "name": "Example Medical Practice"}],
    )
    assert out["summary"] == "s"
    (kw,) = msgs.calls
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert kw["output_config"]["effort"] == "medium"
    assert kw["output_config"]["format"]["schema"] == providers.BOOKING_SCHEMA
    assert "thinking" not in kw and "tool_choice" not in kw
    sent = json.dumps(kw["messages"])
    assert "943 476 5919" not in sent and "01/02/1960" not in sent and "12345678" not in sent
    assert "12 Oct AM" in sent and "Example Medical Practice" in sent
    assert "sk-test" not in sent


def test_anthropic_provider_refusal_and_fallback_model():
    msgs = FakeMessages({}, stop_reason="refusal")
    p = providers.AnthropicProvider("sk-test", "claude-opus-5-5", client=fake_client(msgs))
    with pytest.raises(DomainError) as e:
        p.read_booking(text="x", attachment=None, practices=[], today=TODAY)
    assert e.value.code == "assistant.refused"
    msgs = FakeMessages({"summary": "", "items": [], "questions": []}, model="claude-opus-4-8")
    p = providers.AnthropicProvider("sk-test", "claude-opus-5-5", client=fake_client(msgs))
    p.read_booking(text="x", attachment=None, practices=[], today=TODAY)
    assert p.engine == "ai:claude-opus-4-8"  # recorded which model actually answered


def test_assistant_config_off_by_default_and_key_encrypted(settings, session):
    box = SecretBox(settings)
    assert providers.provider_for(session, settings, box) is None
    with pytest.raises(DomainError):
        providers.save_config(session, box, enabled=True, api_key="short")
    providers.save_config(session, box, enabled=True, api_key="sk-ant-" + "x" * 40)
    cfg = providers.get_config(session)
    assert "x" * 40 not in (cfg.api_key_ciphertext or "")
    pub = providers.config_public(cfg, settings)
    assert pub["ready"] is True and "api_key" not in json.dumps(pub).replace("key_", "")
    assert isinstance(providers.provider_for(session, settings, box), providers.AnthropicProvider)
    providers.save_config(session, box, enabled=False, api_key=None)
    assert providers.provider_for(session, settings, box) is None


# ------------------------------------------------------------------- checks


def test_inbox_findings(session, ready):
    prop, doc = _propose(session)
    found = {f.kind for f in checks.run_checks(session, today=TODAY)}
    assert "proposals_pending" in found and "inbox_waiting" not in found
    doc.created_at = datetime(2026, 10, 1, tzinfo=UTC)
    session.commit()
    assert "inbox_waiting" in {f.kind for f in checks.run_checks(session, today=TODAY)}


# ---------------------------------------------------------------------- API


class FakeProvider:
    engine = "ai:fake"

    def __init__(self):
        self.calls = []

    def read_booking(self, *, text, attachment, practices, today):
        self.calls.append((text, attachment, practices))
        return {
            "summary": "Two sessions.",
            "items": [
                {
                    "date": "2026-10-20",
                    "unit": "am",
                    "hours": None,
                    "practice_id": practices[0]["id"],
                    "practice_name": None,
                    "rate": "610.00",
                    "action": "add",
                    "note": None,
                },
                {
                    "date": "2026-10-21",
                    "unit": "pm",
                    "hours": None,
                    "practice_id": None,
                    "practice_name": "Unknown Surgery",
                    "rate": None,
                    "action": "add",
                    "note": "Practice not on file",
                },
            ],
            "questions": ["Which practice is the 21st at?"],
        }


def test_api_inbox_and_booking_flow(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        p = c.post(
            "/api/v1/practices",
            json={
                "name": "Example Medical Practice",
                "billing_address": "2 Test Road",
                "default_rate": "600.00",
            },
            headers=h,
        ).json()

        # assistant off: rules engine reads the paste
        r = c.post("/api/v1/assistant/booking", json={"text": BOOKING}, headers=h)
        assert r.status_code == 201
        prop = r.json()["proposal"]
        assert prop["engine"] == "rules" and prop["ai"] is False and len(prop["items"]) == 4
        r = c.post(
            f"/api/v1/proposals/{prop['id']}/accept",
            json={"items": [{"index": 0}, {"index": 1}]},
            headers=h,
        )
        assert r.status_code == 200 and len(r.json()["result"]["created"]) == 2
        assert len(c.get("/api/v1/sessions?start=2026-10-01&end=2026-10-31").json()) == 2
        r = c.post(f"/api/v1/proposals/{prop['id']}/undo", headers=h)
        assert r.json()["status"] == "pending"
        assert c.get("/api/v1/sessions?start=2026-10-01&end=2026-10-31").json() == []
        assert (
            c.post(
                f"/api/v1/proposals/{prop['id']}/accept", json={"items": []}, headers=h
            ).status_code
            == 422
        )

        # upload a file, list, read, download, trash, restore
        r = c.post(
            "/api/v1/documents",
            files={"file": ("rota.txt", b"Remittance BACS", "text/plain")},
            headers=h,
        )
        assert r.status_code == 201 and r.json()["kind"] == "remittance"
        doc_id = r.json()["id"]
        lst = c.get("/api/v1/documents").json()
        assert lst["new"] == 2 and {d["id"] for d in lst["documents"]} >= {doc_id}
        assert c.get("/api/v1/documents?q=bacs").json()["documents"][0]["id"] == doc_id
        f = c.get(f"/api/v1/documents/{doc_id}/file")
        assert f.content == b"Remittance BACS" and "attachment" in f.headers["content-disposition"]
        assert (
            c.patch(f"/api/v1/documents/{doc_id}", json={"status": "done"}, headers=h).json()[
                "status"
            ]
            == "done"
        )
        assert c.delete(f"/api/v1/documents/{doc_id}", headers=h).status_code == 204
        assert c.get(f"/api/v1/documents/{doc_id}").status_code == 404
        assert c.post(f"/api/v1/documents/{doc_id}/restore", headers=h).status_code == 200

        # settings: key never echoed
        r = c.put(
            "/api/v1/settings/assistant",
            json={"enabled": True, "api_key": "sk-ant-" + "y" * 40},
            headers=h,
        )
        assert r.json()["ready"] is True and "y" * 40 not in r.text

        # assistant on: the (fake) provider proposes; AI suggestions are labelled
        fake = FakeProvider()
        app.state.ai_provider_factory = lambda s: fake
        r = c.post("/api/v1/assistant/booking", json={"text": "Booking for 20/21 Oct"}, headers=h)
        prop = r.json()["proposal"]
        assert prop["ai"] is True and prop["questions"]
        assert fake.calls[0][2] == [{"id": p["id"], "name": "Example Medical Practice"}]
        a, b = prop["items"]
        assert a["selected"] and a["rate"] == "610.00"
        assert "needs_practice" in b["flags"] and b["practice_name"] == "Unknown Surgery"
        r = c.post(
            f"/api/v1/proposals/{prop['id']}/accept",
            headers=h,
            json={"items": [{"index": 0}, {"index": 1, "practice_id": p["id"]}]},
        )
        assert r.json()["status"] == "accepted"
        pending = c.get("/api/v1/proposals").json()
        assert [x["engine"] for x in pending] == ["rules"]  # the undone one; AI one accepted
        assert c.get("/api/v1/overview").status_code == 200


def test_upload_size_limit(settings, session, monkeypatch):
    monkeypatch.setattr(documents, "MAX_BYTES", 10)
    with pytest.raises(DomainError) as e:
        documents.add_upload(session, settings, "a.txt", "text/plain", b"x" * 11)
    assert e.value.code == "document.too_large"
    assert session.query(Document).count() == 0 and session.query(Proposal).count() == 0


def test_correspondence_links_documents_to_invoices(settings, session, ready):
    import uuid

    from locuvi.models import InvoiceEvent
    from locuvi.services import invoices as svc

    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 8, 3))])
    d = diary.invoice_month(session, ready.id, "2026-08")
    inv = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    session.expire_all()
    number = inv.invoice_number
    remit = documents.add_paste(session, f"Remittance advice: BACS for {number.lower()} paid")
    assert remit.invoice_id == inv.id  # number found, case/punctuation-insensitive
    other = documents.add_paste(session, "Remittance for several invoices")
    assert other.invoice_id is None
    documents.update(session, other, invoice_id=inv.id)
    session.add(
        InvoiceEvent(
            invoice_id=inv.id,
            event_type="emailed",
            metadata_json={"to": ["a@example.invalid"], "subject": "Invoice"},
        )
    )
    session.commit()
    log = documents.correspondence(session, inv.id)
    assert sorted(x["type"] for x in log) == ["document", "document", "sent"]
    assert {x.get("id") for x in log if x["type"] == "document"} == {remit.id, other.id}
