"""Microsoft (Outlook.com / Microsoft 365 / NHSmail) mail reading against a fake Microsoft.

No real Microsoft endpoint is ever called; fictional data only.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, unquote

import httpx
import pytest
from test_mailbox import mail

from locuvi.errors import DomainError
from locuvi.models import Document, MailFolderState, Proposal
from locuvi.secrets_store import SecretBox
from locuvi.services import mail_microsoft, mailbox

TODAY = date(2026, 10, 8)
CLIENT_ID = "00000000-0000-0000-0000-000000000000"


class FakeMicrosoft:
    """Login + Graph. Fails the test on any write request to Graph."""

    def __init__(self, folders, *, consent=True, approve_after=1, slow_down=False):
        self.folders = folders  # {id: (name, [(msg_id, received, raw)])}, list in arrival order
        self.consent = consent
        self.polls_left = approve_after
        self.slow_down = slow_down
        self.forget_delta = False
        self.refresh = "refresh-token-1"
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = req.url
        if url.host == "login.microsoftonline.com":
            assert req.method == "POST"
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            assert form["client_id"] == CLIENT_ID
            if url.path.endswith("/devicecode"):
                assert "Mail.Read" in form["scope"] and "ReadWrite" not in form["scope"]
                return httpx.Response(200, json={
                    "device_code": "secret-device-code", "user_code": "ABCD-1234",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "expires_in": 900, "interval": 1,
                })  # fmt: skip
            if form["grant_type"].endswith("device_code"):
                assert form["device_code"] == "secret-device-code"
                if self.polls_left > 0:
                    self.polls_left -= 1
                    error = "slow_down" if self.slow_down else "authorization_pending"
                    return httpx.Response(400, json={"error": error})
                if not self.consent:
                    return httpx.Response(400, json={
                        "error": "invalid_grant",
                        "error_description": "AADSTS90094: An administrator ... approval.",
                    })  # fmt: skip
                return self._tokens()
            assert form["grant_type"] == "refresh_token"
            if form["refresh_token"] != self.refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return self._tokens()
        assert url.host == "graph.microsoft.com"
        assert req.method == "GET", "Graph must only ever be read"
        assert req.headers["authorization"] == "Bearer access-token"
        path = unquote(url.raw_path.decode().split("?")[0])
        if path == "/v1.0/me":
            return httpx.Response(200, json={"mail": "alex@example.invalid"})
        if path == "/v1.0/me/mailFolders":
            return httpx.Response(200, json={"value": [
                {"id": fid, "displayName": name, "childFolderCount": 1 if fid == "inbox-id" else 0}
                for fid, (name, _) in self.folders.items() if fid != "child-id"
            ]})  # fmt: skip
        if path == "/v1.0/me/mailFolders/inbox-id/childFolders":
            name = self.folders["child-id"][0]
            return httpx.Response(200, json={"value": [{"id": "child-id", "displayName": name}]})
        if path.endswith("/messages/delta"):
            # delta: the first call lists the folder, later calls only what arrived since
            # (in arrival order, whatever the received date). Pages of 1 to test paging.
            assert req.headers["prefer"] == "odata.maxpagesize=50"
            fid = path.split("/")[4]
            q = parse_qs(url.query.decode())
            msgs = self.folders[fid][1]
            if "$deltatoken" in q or "$skiptoken" in q:
                if self.forget_delta:
                    self.forget_delta = False
                    return httpx.Response(410, json={"error": {"code": "syncStateNotFound"}})
                pos = int((q.get("$deltatoken") or q["$skiptoken"])[0])
                todo = list(range(pos, len(msgs)))
            else:
                since = q["$filter"][0].split(" ge ")[1]
                todo = [i for i, m in enumerate(msgs) if m[1] >= since]
            base = f"https://graph.microsoft.com/v1.0/me/mailFolders/{fid}/messages/delta"
            if not todo:
                return httpx.Response(
                    200, json={"value": [], "@odata.deltaLink": f"{base}?$deltatoken={len(msgs)}"}
                )
            i = todo[0]
            mid, when, _ = msgs[i]
            page = {"value": [{"id": mid, "internetMessageId": f"<{mid}@example.invalid>",
                               "receivedDateTime": when}]}  # fmt: skip
            if len(todo) > 1:
                page["@odata.nextLink"] = f"{base}?$skiptoken={todo[1]}"
            else:
                page["@odata.deltaLink"] = f"{base}?$deltatoken={len(msgs)}"
            return httpx.Response(200, json=page)
        if path.endswith("/$value"):
            mid = path.split("/")[4]
            for _, msgs in self.folders.values():
                for m in msgs:
                    if m[0] == mid:
                        return httpx.Response(200, content=m[2])
        return httpx.Response(404, json={})

    def _tokens(self) -> httpx.Response:
        n = int(self.refresh.rsplit("-", 1)[1]) + 1
        self.refresh = f"refresh-token-{n}"
        return httpx.Response(200, json={
            "access_token": "access-token", "refresh_token": self.refresh,
            "scope": "Mail.Read User.Read" if self.consent else "User.Read",
        })  # fmt: skip


def booking(mid, when, text="Locum session 23 October AM £600"):
    return (mid, when, mail("Booking", text, f"<{mid}@example.invalid>"))


@pytest.fixture
def box(settings):
    return SecretBox(settings)


@pytest.fixture
def fake():
    return FakeMicrosoft({
        "inbox-id": ("Inbox", []),
        "child-id": ("Locum", [booking("m1", "2026-10-01T09:00:00Z")]),
    })  # fmt: skip


def sign_in(session, box, fake):
    start = mailbox.ms_start(CLIENT_ID, "organizations", fake.transport())
    assert start["user_code"] == "ABCD-1234" and "device_code" not in str(start)
    assert mailbox.ms_poll(session, box, fake.transport())["status"] == "pending"
    return mailbox.ms_poll(session, box, fake.transport())


def test_sign_in_keeps_only_an_encrypted_token(session, box, fake):
    done = sign_in(session, box, fake)
    assert done == {"status": "done", "username": "alex@example.invalid"}
    cfg = mailbox.get_config(session)
    pub = mailbox.config_public(cfg)
    assert (
        pub["provider"] == "microsoft"
        and pub["ms_signed_in"]
        and pub["ms_tenant"] == "organizations"
    )
    assert "refresh-token" not in str(pub) and "refresh-token" not in cfg.ms_token_ciphertext
    with pytest.raises(DomainError) as e:  # the code is single-use
        mailbox.ms_poll(session, box, fake.transport())
    assert e.value.code == "mailbox.ms_expired"


def test_slow_down_lengthens_the_wait(session, box):
    fake = FakeMicrosoft({}, approve_after=2, slow_down=True)
    start = mailbox.ms_start(CLIENT_ID, "common", fake.transport())
    first = mailbox.ms_poll(session, box, fake.transport())
    second = mailbox.ms_poll(session, box, fake.transport())
    assert (first["interval"], second["interval"]) == (
        start["interval"] + 5,
        start["interval"] + 10,
    )
    assert mailbox.ms_poll(session, box, fake.transport())["status"] == "done"


def test_stale_poll_neither_saves_nor_ends_the_new_sign_in(session, box, monkeypatch):
    fake = FakeMicrosoft({}, approve_after=0)
    mailbox.ms_start(CLIENT_ID, "common", fake.transport())
    stale = dict(mail_microsoft._pending)
    mailbox.ms_start(CLIENT_ID, "common", fake.transport())  # owner cancelled and restarted
    newer = dict(mail_microsoft._pending)
    newer["device_code"] = "newer-code"
    mail_microsoft._pending.update(newer)
    real = mail_microsoft._pending_lock

    class Swap:  # the poll copies the *stale* attempt, as if it was already in flight
        def __enter__(self):
            real.acquire()
            if not getattr(self, "used", False):
                self.used = True
                self.saved = dict(mail_microsoft._pending)
                mail_microsoft._pending.clear()
                mail_microsoft._pending.update(stale)
            elif hasattr(self, "saved"):
                mail_microsoft._pending.clear()
                mail_microsoft._pending.update(self.saved)
                del self.saved

        def __exit__(self, *exc):
            real.release()

    monkeypatch.setattr(mail_microsoft, "_pending_lock", Swap())
    with pytest.raises(DomainError) as e:
        mailbox.ms_poll(session, box, fake.transport())
    assert e.value.code == "mailbox.ms_expired"
    assert not mailbox.get_config(session).ms_token_ciphertext
    assert mail_microsoft._pending["device_code"] == "newer-code"


def test_bad_app_id_and_missing_approval(session, box):
    with pytest.raises(DomainError) as e:
        mailbox.ms_start("not-a-guid", "common")
    assert e.value.code == "mailbox.ms_client_id"
    fake = FakeMicrosoft({}, consent=False, approve_after=0)
    mailbox.ms_start(CLIENT_ID, "organizations", fake.transport())
    with pytest.raises(DomainError) as e:
        mailbox.ms_poll(session, box, fake.transport())
    assert e.value.code == "mailbox.ms_admin_consent"
    assert not mailbox.get_config(session).ms_token_ciphertext


def test_folders_scan_and_resume_read_only(settings, session, box, fake, ready):
    sign_in(session, box, fake)
    folders = mailbox.list_folders(session, settings, box, factory=fake.transport())
    assert folders[0]["label"] == "Inbox"
    assert {"name": "child-id", "label": "Inbox / Locum"} in folders
    mailbox.save_config(session, box, {"enabled": True, "folders": ["child-id"]})
    assert mailbox.config_public(mailbox.get_config(session))["folder_labels"] == {
        "child-id": "Inbox / Locum"
    }

    res = mailbox.scan(session, settings, box, factory=fake.transport(), today=TODAY)
    assert res["checked"] == 1 and res["bookings"] == 1 and res["to_review"] == 1
    doc = session.query(Document).one()
    assert doc.source == "email" and doc.mail_folder == "child-id"
    assert session.query(Proposal).count() == 1

    # next scan reads only what was added since -- including an old message the owner
    # filed into the folder by hand (received before the last scan)
    fake.folders["child-id"][1].append(
        booking("m2", "2026-09-20T10:00:00Z", "Remittance advice BACS paid")
    )
    res = mailbox.scan(session, settings, box, factory=fake.transport(), today=TODAY)
    assert res["checked"] == 1 and res["remittances"] == 1
    assert "deltatoken=2" in session.get(MailFolderState, "child-id").cursor
    res = mailbox.scan(session, settings, box, factory=fake.transport(), today=TODAY)
    assert res["checked"] == 0

    # Microsoft forgot the position: read again from the start, nothing imported twice
    fake.forget_delta = True
    res = mailbox.scan(session, settings, box, factory=fake.transport(), today=TODAY)
    assert res["checked"] == 2 and res["already_seen"] == 2
    assert session.query(Document).count() == 2
    assert all(r.method == "GET" for r in fake.requests if r.url.host == "graph.microsoft.com")
    assert fake.refresh.endswith("-7")  # sign-in, folders, 2 scans: each kept the new one


def test_expired_sign_in_is_reported(settings, session, box, fake):
    sign_in(session, box, fake)
    mailbox.list_folders(session, settings, box, factory=fake.transport())
    mailbox.save_config(session, box, {"enabled": True, "folders": ["child-id"]})
    fake.refresh = "revoked-0"
    with pytest.raises(DomainError) as e:
        mailbox.scan(session, settings, box, factory=fake.transport(), today=TODAY)
    assert e.value.code == "mailbox.ms_signed_out"
    assert mailbox.get_config(session).last_error == "mailbox.ms_signed_out"


def test_switching_account_type_forgets_folders(settings, session, box, fake):
    mailbox.save_config(session, box, {
        "enabled": True, "host": "imap.gmail.com", "username": "alex@example.invalid",
        "password": "app-password-0000", "folders": ["INBOX"],
    })  # fmt: skip
    session.add(MailFolderState(folder="INBOX", uidvalidity=7, last_uid=40))
    session.commit()
    sign_in(session, box, fake)
    cfg = mailbox.get_config(session)
    assert cfg.provider == "microsoft" and cfg.folders == [] and not cfg.enabled
    assert session.query(MailFolderState).count() == 0
    # folders Microsoft never listed (e.g. the old IMAP names) are not kept
    mailbox.list_folders(session, settings, box, factory=fake.transport())
    cfg = mailbox.save_config(session, box, {"folders": ["INBOX", "child-id"]})
    assert cfg.folders == ["child-id"]
    # switching back to IMAP drops the Microsoft folder ids sent along by the page
    cfg = mailbox.save_config(session, box, {
        "provider": "imap", "host": "imap.gmail.com", "username": "alex@example.invalid",
        "folders": ["child-id"],
    })  # fmt: skip
    assert cfg.provider == "imap" and cfg.folders == []
    cfg.provider = "microsoft"
    session.commit()
    with pytest.raises(DomainError):  # must sign in again after signing out
        mailbox.ms_sign_out(session)
        mailbox.save_config(session, box, {"enabled": True, "folders": ["child-id"]})


def test_api_microsoft_flow(settings, fake):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    app = create_app(settings)
    app.state.ms_transport = fake.transport()
    with TestClient(app) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        r = c.post("/api/v1/settings/mailbox/microsoft/start", headers=h,
                   json={"client_id": CLIENT_ID, "tenant": "consumers"})  # fmt: skip
        assert r.status_code == 200 and r.json()["user_code"] == "ABCD-1234"
        assert "secret-device-code" not in r.text
        assert (
            c.post("/api/v1/settings/mailbox/microsoft/poll", headers=h).json()["status"]
            == "pending"
        )
        r = c.post("/api/v1/settings/mailbox/microsoft/poll", headers=h).json()
        assert r["status"] == "done" and r["config"]["username"] == "alex@example.invalid"
        names = [
            f["name"]
            for f in c.post("/api/v1/settings/mailbox/folders", headers=h).json()["folders"]
        ]
        assert "child-id" in names
        body = {"enabled": True, "provider": "microsoft", "folders": ["child-id"]}
        r = c.put("/api/v1/settings/mailbox", headers=h, json=body)
        assert r.status_code == 200 and "refresh-token" not in r.text
        assert c.post("/api/v1/mailbox/scan", headers=h).json()["bookings"] == 1
        r = c.delete("/api/v1/settings/mailbox/microsoft", headers=h).json()
        assert not r["ms_signed_in"] and not r["enabled"]


def test_graph_ids_are_escaped():
    assert mail_microsoft._q("a/b?c=d") == "a%2Fb%3Fc%3Dd"
