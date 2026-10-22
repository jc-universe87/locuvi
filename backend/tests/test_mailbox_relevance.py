"""Which emails the folder scan keeps: realistic messages with real headers. Fictional data only.

Every real email has a Date header and many use words like "session", "clinic" or "paid", so
those alone must not make an email look like a booking or a remittance.
"""

from __future__ import annotations

import email
import email.policy
from datetime import date

import pytest
from test_mailbox import FakeIMAP, configure

from locuvi.models import Document, Proposal
from locuvi.secrets_store import SecretBox
from locuvi.services import documents, mailbox, proposals

TODAY = date(2026, 10, 8)


def mail(subject, body, *, sender="someone@example.invalid", msgid=None, **headers):
    m = email.message.EmailMessage()
    m["From"] = sender
    m["To"] = "alex@example.invalid"
    m["Date"] = "Mon, 05 Oct 2026 09:12:00 +0100"
    m["Subject"] = subject
    m["Message-ID"] = msgid or f"<{abs(hash(subject + body))}@example.invalid>"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m


def kind(m, known=(set(), set(), [])):
    return mailbox.classify(m, documents.email_text(m), TODAY, known)


PRACTICE = (
    {"rota@examplesurgery.invalid"},
    {"examplesurgery.invalid"},
    ["example medical practice"],
)


@pytest.mark.parametrize(
    "m",
    [
        mail(
            "Your flu clinic appointment", "Your appointment is confirmed. See you at the clinic."
        ),
        mail("Team drinks", "Shall we meet after the morning session? It was good to catch up."),
        mail("Your order has been paid", "Thank you, your order of £24.99 has been paid."),
        mail(
            "Autumn locum jobs",
            "50 new locum sessions near you from 12 October, £90/hour. Unsubscribe here.",
            List_Unsubscribe="<mailto:unsubscribe@example.invalid>",
        ),
        mail(
            "Automatic reply: locum session",
            "I'm out of the office until 12 October and will reply when I'm back.",
            Auto_Submitted="auto-replied",
        ),
        mail(
            "Re: catch up",
            "Thanks, sounds good.\n\nOn Mon 12 Oct 2026 at 09:00, Sam wrote:\n> locum session AM?",
        ),
        mail("CPD webinar", "Join our webinar for GPs on 14 October. Register now."),
    ],
    ids=[
        "clinic-appointment",
        "colleague",
        "shop-paid",
        "agency-newsletter",
        "out-of-office",
        "quoted-reply",
        "webinar",
    ],  # fmt: skip
)
def test_everyday_emails_are_not_kept(m):
    assert kind(m) is None


@pytest.mark.parametrize(
    "m, known",
    [
        (mail("Locum booking", "Could you do a locum session on Tuesday 13 October AM?"), None),
        (
            mail(
                "Next week",
                "Hi Alex, please can you cover Wed 14 Oct PM? Same rate as before.",
                sender="Practice Manager <rota@examplesurgery.invalid>",
            ),
            PRACTICE,
        ),
        (
            mail(
                "Fwd: sessions",
                "See below.\n\nFrom: Rota Team\nSent: Monday, 5 October 2026 10:32\n"
                "Subject: sessions\n\nExample Medical Practice would like to book you for "
                "15 October, morning surgery, £600.",
            ),
            PRACTICE,
        ),
        (
            mail(
                "Booking confirmation",
                "Your booking is confirmed.\nDate: Friday 16 October\nSession: AM\nFee: £620",
                sender="no-reply@agency.invalid",
            ),
            None,
        ),
    ],
    ids=[
        "locum-request",
        "known-practice-no-locum-word",
        "forwarded-booking",
        "agency-confirmation",
    ],
)
def test_bookings_are_kept(m, known):
    assert kind(m, known or (set(), set(), [])) == "booking"


def test_payment_notices():
    assert kind(mail("Remittance advice", "BACS payment of £1,200.00 sent.")) == "remittance"
    assert (
        kind(mail("Invoice LOC-2026-0004", "Your invoice has been paid: £1,240.00."))
        == "remittance"
    )
    paid = mail("Payment", "We've paid £600 today.", sender="accounts@examplesurgery.invalid")
    assert kind(paid, PRACTICE) == "remittance"
    assert kind(mail("Your order", "Payment of £12.00 received, thanks.")) is None


def test_known_senders_ignore_shared_domains(session, ready, monkeypatch):
    # a stand-in for shared domains such as nhs.net, so the fixture stays fictional
    monkeypatch.setattr(mailbox, "_SHARED_DOMAINS", {"shared.invalid"})
    ready.billing_email = "practice.manager@shared.invalid"
    session.commit()
    addresses, domains, names = mailbox.known_senders(session)
    assert addresses == {"practice.manager@shared.invalid"} and domains == set()
    assert names == ["example medical practice"]


def test_scan_keeps_only_relevant_and_tidies_earlier_junk(settings, session, ready):
    box = SecretBox(settings)
    # an email kept by the old, looser check: a newsletter mentioning "sessions"
    junk = mail("Our newsletter", "New yoga sessions start 12 October. Unsubscribe.")
    old = documents.add_upload(
        session, settings, "newsletter.eml", "message/rfc822", junk.as_bytes()
    )
    old.source, old.kind, old.message_id = "email", "booking", junk["Message-ID"]
    stale = Proposal(kind="booking", document_id=old.id, status="pending", payload_json={})
    session.add(stale)
    # one the owner already dealt with stays, whatever it says
    dealt = documents.add_upload(session, settings, "x.eml", "message/rfc822",
                                 mail("Hello", "Nothing to see.").as_bytes())  # fmt: skip
    dealt.source, dealt.status = "email", "done"
    session.commit()
    assert stale in proposals.pending(session)

    folders = {"Locum bookings": {
        1: mail("Locum session", "Locum session Tuesday 13 October PM, £600.").as_bytes(),
        2: mail("Team drinks", "After the morning session on 13 October?").as_bytes(),
        3: mail("Offers", "Clinic offers 12 October.", List_Id="<o.example.invalid>").as_bytes(),
    }}  # fmt: skip
    configure(session, box)
    res = mailbox.scan(session, settings, box, factory=lambda cfg: FakeIMAP(folders), today=TODAY)
    assert res["checked"] == 3 and res["bookings"] == 1 and res["skipped"] == 2
    assert res["tidied"] == 1
    session.refresh(old)
    assert old.deleted_at is not None  # in Recently deleted, can be restored
    assert stale not in proposals.pending(session)  # its suggestion is hidden with it
    session.refresh(dealt)
    assert dealt.deleted_at is None
    kept = session.query(Document).filter(Document.deleted_at.is_(None), Document.source == "email")
    assert sorted(d.filename for d in kept) == ["Locum session.eml", "x.eml"]
