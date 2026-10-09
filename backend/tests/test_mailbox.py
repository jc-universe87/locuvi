"""Mail folder scanning against a fake IMAP server. Fictional data only."""

from __future__ import annotations

import imaplib
from datetime import date
from decimal import Decimal
from email.message import EmailMessage

import pytest

from locuvi.errors import DomainError
from locuvi.models import Document, Proposal
from locuvi.secrets_store import SecretBox
from locuvi.services import checks, diary, mailbox

TODAY = date(2026, 10, 8)


def mail(subject, body, msgid, attachment=None):
    m = EmailMessage()
    m["From"] = "rota@example.invalid"
    m["To"] = "alex@example.invalid"
    m["Subject"] = subject
    m["Message-ID"] = msgid
    m.set_content(body)
    if attachment:
        m.add_attachment(attachment.encode(), maintype="text", subtype="plain", filename="rota.txt")
    return m.as_bytes()


class FakeIMAP:
    """Just enough IMAP; fails the test on any write command or non-read-only select."""

    def __init__(self, folders, password="app-password-0000", validity=7):
        self.folders, self.password, self.validity = folders, password, validity
        self.selected = None
        self.commands = []

    def login(self, user, pw):
        if pw != self.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"logged in"]

    def list(self):
        rows = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noselect \\HasChildren) "/" "[Gmail]"']
        rows += [f'(\\HasNoChildren) "/" "{f}"'.encode() for f in self.folders if f != "INBOX"]
        rows.append(b'(\\HasNoChildren) "/" "&AMk-quipe"')  # modified UTF-7 "Équipe"
        return "OK", rows

    def select(self, name, readonly=False):
        assert readonly is True, "folders must be opened read-only"
        self.selected = name.strip('"')
        self.commands.append(("SELECT", self.selected))
        if self.selected not in self.folders:
            return "NO", [b"no such folder"]
        return "OK", [str(len(self.folders[self.selected])).encode()]

    def response(self, code):
        return code, [str(self.validity).encode()]

    def uid(self, command, *args):
        self.commands.append((command, args))
        msgs = self.folders[self.selected]
        if command == "SEARCH":
            crit = [a for a in args if a is not None]
            if crit[0] == "UID":
                start = int(crit[1].split(":")[0])
                found = [u for u in msgs if u >= start] or [max(msgs)]
            else:
                found = list(msgs)
            return "OK", [" ".join(str(u) for u in sorted(found)).encode()]
        if command == "FETCH":
            uid, what = int(args[0]), args[1]
            raw = msgs[uid]
            if what == "(RFC822.SIZE)":
                return "OK", [f"1 (UID {uid} RFC822.SIZE {len(raw)})".encode()]
            assert what == "(BODY.PEEK[])", "messages must be fetched with PEEK"
            return "OK", [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(f"unexpected IMAP command {command}")

    def logout(self):
        return "BYE", []


@pytest.fixture
def box(settings):
    return SecretBox(settings)


def configure(session, box, folders=("Locum bookings",), username="alex@example.invalid"):
    return mailbox.create_account(
        session,
        box,
        {
            "enabled": True,
            "host": "imap.example.invalid",
            "port": 993,
            "security": "ssl",
            "username": username,
            "password": "app-password-0000",
            "folders": list(folders),
            "since_days": 90,
        },
    )


def test_config_validation_and_secret(session, box):
    with pytest.raises(DomainError):
        mailbox.create_account(session, box, {"enabled": True, "host": "imap.example.invalid"})
    with pytest.raises(DomainError) as e:
        mailbox.create_account(
            session,
            box,
            {
                "enabled": True,
                "host": "imap.example.invalid",
                "username": "u",
                "password": "p",
                "folders": [],
            },
        )
    assert e.value.code == "mailbox.no_folders"
    cfg = configure(session, box)
    pub = mailbox.account_public(cfg)
    assert pub["password_set"] and "app-password" not in str(pub)
    assert "app-password" not in (cfg.password_ciphertext or "")


def test_list_folders_only_selectable_and_decoded(settings, session, box):
    acc = configure(session, box)
    fake = FakeIMAP({"INBOX": {}, "Locum bookings": {}})
    folders = mailbox.list_folders(session, settings, box, acc.id, factory=lambda cfg: fake)
    labels = [f["label"] for f in folders]
    assert labels[0] == "INBOX" and "[Gmail]" not in labels
    assert "Équipe" in labels and {"name": "&AMk-quipe", "label": "Équipe"} in folders


def test_scan_reads_only_chosen_folders_and_verifies_against_diary(settings, session, box, ready):
    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 10, 12), "am")])
    folders = {
        "INBOX": {1: mail("Private", "Dinner on 12 October?", "<p1@example.invalid>")},
        "Locum bookings": {
            10: mail(
                "Locum booking confirmed",
                "Example Medical Practice confirms locum session Monday 12 October AM. Fee £600.",
                "<b1@example.invalid>",
            ),  # already in the diary, same rate
            11: mail(
                "Sessions next week",
                "Locum cover at Example Medical Practice: Tue 13 Oct PM and Wed 14 Oct AM, "
                "£620 per session.",
                "<b2@example.invalid>",
            ),
            12: mail(
                "Rate change",
                "Example Medical Practice locum session 12 October AM at £650.",
                "<b3@example.invalid>",
            ),  # booked, but the fee differs
            13: mail("Newsletter", "Our autumn newsletter. Read more.", "<n1@example.invalid>"),
            14: mail(
                "Remittance advice", "BACS payment of £1,200.00 sent.", "<r1@example.invalid>"
            ),
        },
    }
    configure(session, box)
    fake = FakeIMAP(folders)
    res = mailbox.scan(session, settings, box, factory=lambda cfg: fake, today=TODAY)
    assert res["checked"] == 5 and res["skipped"] == 1
    assert res["bookings"] == 3 and res["remittances"] == 1
    assert res["already_booked"] == 1 and res["to_review"] == 2
    # INBOX was never opened; no write commands (the fake asserts PEEK + read-only)
    assert ("SELECT", "INBOX") not in fake.commands
    docs = {d.message_id: d for d in session.query(Document).all()}
    assert "<n1@example.invalid>" not in docs and "<p1@example.invalid>" not in docs
    assert docs["<b1@example.invalid>"].status == "done"  # verified: nothing to do
    assert docs["<b1@example.invalid>"].source == "email"
    assert docs["<b1@example.invalid>"].mail_folder == "Locum bookings"

    props = {p.document_id: p for p in session.query(Proposal).all()}
    assert props[docs["<b1@example.invalid>"].id].status == "verified"
    new = props[docs["<b2@example.invalid>"].id].payload_json["items"]
    assert [(i["date"], i["unit"], i["rate"], i["selected"]) for i in new] == [
        ("2026-10-13", "pm", "620.00", True),
        ("2026-10-14", "am", "620.00", True),
    ]
    differs = props[docs["<b3@example.invalid>"].id].payload_json["items"][0]
    assert differs["flags"] == ["duplicate", "rate_differs"] and differs["diary_rate"] == "600.00"

    # second scan resumes after the last UID: nothing new
    res2 = mailbox.scan(session, settings, box, factory=lambda cfg: fake, today=TODAY)
    assert res2["checked"] == 0 and session.query(Document).count() == 4
    # a new message arrives
    folders["Locum bookings"][15] = mail(
        "One more", "Locum session 20 October PM £600", "<b4@example.invalid>"
    )
    res3 = mailbox.scan(session, settings, box, factory=lambda cfg: fake, today=TODAY)
    assert res3["checked"] == 1 and res3["to_review"] == 1


def test_attachment_text_is_read(settings, session, box, ready):
    folders = {
        "Locum bookings": {
            1: mail(
                "Rota attached",
                "Please see the attached rota.",
                "<a1@example.invalid>",
                attachment="Locum sessions: 21 October AM, £600",
            )
        }
    }
    configure(session, box)
    res = mailbox.scan(session, settings, box, factory=lambda cfg: FakeIMAP(folders), today=TODAY)
    assert res["to_review"] == 1


def test_uidvalidity_change_rescans_without_duplicates(settings, session, box, ready):
    folders = {
        "Locum bookings": {
            5: mail("Booking", "Locum session 22 October AM £600", "<v1@example.invalid>")
        }
    }
    configure(session, box)
    mailbox.scan(session, settings, box, factory=lambda cfg: FakeIMAP(folders), today=TODAY)
    res = mailbox.scan(
        session, settings, box, factory=lambda cfg: FakeIMAP(folders, validity=8), today=TODAY
    )
    assert res["checked"] == 1 and res["already_seen"] == 1
    assert session.query(Document).count() == 1


def test_login_failure_is_recorded_as_finding(settings, session, box, ready):
    configure(session, box)
    with pytest.raises(DomainError) as e:
        mailbox.scan(
            session, settings, box, factory=lambda cfg: FakeIMAP({}, password="other"), today=TODAY
        )
    assert e.value.code == "mailbox.auth_failed"
    assert "mailbox_failed" in {f.kind for f in checks.run_checks(session, today=TODAY)}


def test_several_accounts_each_with_own_folders_and_errors(settings, session, box, ready):
    """Two mailboxes with the same folder name keep separate progress; one failing account
    doesn't stop the other, and only the failing one is reported."""
    work = configure(session, box, username="work@example.invalid")
    home = configure(session, box, username="home@example.invalid")
    servers = {
        "work@example.invalid": FakeIMAP({"Locum bookings": {
            7: mail("Booking", "Locum session 23 October AM £600", "<w1@example.invalid>"),
        }}),
        "home@example.invalid": FakeIMAP({"Locum bookings": {
            7: mail("Booking", "Locum session 24 October AM £600", "<h1@example.invalid>"),
        }}),
    }  # fmt: skip
    res = mailbox.scan(
        session, settings, box, factory=lambda acc: servers[acc.username], today=TODAY
    )
    assert res["checked"] == 2 and res["bookings"] == 2 and res["errors"] == []
    from locuvi.models import MailFolderState

    assert {(st.account_id, st.last_uid) for st in session.query(MailFolderState)} == {
        (work.id, 7), (home.id, 7)
    }  # fmt: skip

    servers["home@example.invalid"].password = "changed"
    res = mailbox.scan(
        session, settings, box, factory=lambda acc: servers[acc.username], today=TODAY
    )
    assert res["errors"] == [
        {"account_id": home.id, "label": "home@example.invalid", "error": "mailbox.auth_failed"}
    ]
    found = [f for f in checks.run_checks(session, today=TODAY) if f.kind == "mailbox_failed"]
    assert [f.params["account"] for f in found] == ["home@example.invalid"]

    # removing an account stops it (undo restores it); after 30 days it is purged
    mailbox.remove_account(session, home.id)
    assert [a.id for a in mailbox.list_accounts(session)] == [work.id]
    mailbox.restore_account(session, home.id)
    mailbox.remove_account(session, home.id)
    from datetime import timedelta

    from locuvi.models import utcnow

    assert mailbox.purge_removed(session) == 0
    assert mailbox.purge_removed(session, now=utcnow() + timedelta(days=29)) == 0
    assert mailbox.purge_removed(session, now=utcnow() + timedelta(days=31)) == 1
    assert {st.account_id for st in session.query(MailFolderState)} == {work.id}
    with pytest.raises(DomainError):
        mailbox.restore_account(session, home.id)


def test_api_mailbox_flow(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    app = create_app(settings)
    folders = {
        "Locum bookings": {
            1: mail("Booking", "Locum session 23 October AM £600", "<x1@example.invalid>")
        }
    }
    app.state.imap_factory = lambda cfg: FakeIMAP(folders)
    with TestClient(app) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        c.post(
            "/api/v1/practices",
            json={
                "name": "Example Medical Practice",
                "billing_address": "2 Test Road",
                "default_rate": "600.00",
            },
            headers=h,
        )
        body = {
            "enabled": False,
            "host": "imap.example.invalid",
            "username": "alex@example.invalid",
            "password": "app-password-0000",
        }
        r = c.post("/api/v1/settings/mailboxes", json=body, headers=h)
        assert r.status_code == 201
        acc = r.json()["id"]
        names = [
            f["name"]
            for f in c.post(f"/api/v1/settings/mailboxes/{acc}/folders", headers=h).json()[
                "folders"
            ]
        ]
        assert "Locum bookings" in names
        r = c.put(
            f"/api/v1/settings/mailboxes/{acc}",
            headers=h,
            json={**body, "password": None, "enabled": True, "folders": ["Locum bookings"]},
        )
        assert r.json()["password_set"] and "app-password" not in r.text
        r = c.post("/api/v1/mailbox/scan", headers=h)
        assert r.status_code == 200 and r.json()["to_review"] == 1
        accounts = c.get("/api/v1/settings/mailboxes").json()["accounts"]
        assert accounts[0]["last_result"]["bookings"] == 1
        prop = c.get("/api/v1/proposals").json()[0]
        assert prop["items"][0]["rate"] == "600.00" and Decimal(prop["items"][0]["rate"]) == 600
