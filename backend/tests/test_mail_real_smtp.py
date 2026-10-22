"""Sending through a real SMTP server: STARTTLS (587-style) and SSL/TLS (465-style), with login.

A disposable aiosmtpd server on localhost with a throwaway certificate authority, so the real
smtplib + TLS path runs (the other email tests use a fake connection). Fictional data only.
"""

from __future__ import annotations

import datetime as dt
import email
import socket
import ssl
from dataclasses import replace

import pytest

aiosmtpd = pytest.importorskip("aiosmtpd")

from aiosmtpd.controller import Controller  # noqa: E402
from aiosmtpd.smtp import AuthResult, LoginPassword  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from locuvi import db, mail  # noqa: E402
from locuvi.config import WebDavAllowlist  # noqa: E402
from locuvi.errors import DomainError  # noqa: E402
from locuvi.models import Invoice  # noqa: E402
from locuvi.secrets_store import SecretBox  # noqa: E402
from locuvi.storage.local import resolve  # noqa: E402

USER, PASSWORD = "alex@example.invalid", "smtp-app-password"


def _certs(tmp_path):
    """A throwaway CA and a server certificate for localhost, signed by it."""
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Locuvi test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    (tmp_path / "ca.pem").write_bytes(ca.public_bytes(pem))
    (tmp_path / "server.pem").write_bytes(cert.public_bytes(pem))
    (tmp_path / "server.key").write_bytes(
        key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    return str(tmp_path / "ca.pem"), server_ctx


class Inbox:
    def __init__(self):
        self.messages: list[tuple[list[str], bytes]] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd hook
        self.messages.append((list(envelope.rcpt_tos), envelope.content))
        return "250 OK"


def _auth(server, session, envelope, mechanism, auth_data):
    ok = isinstance(auth_data, LoginPassword) and (
        auth_data.login.decode(),
        auth_data.password.decode(),
    ) == (USER, PASSWORD)
    return AuthResult(success=ok, handled=False)  # False: the server replies 535 itself


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp_servers(tmp_path):
    """(inbox, ca_file, starttls_port, ssl_port): two real servers that require TLS + login."""
    ca_file, server_ctx = _certs(tmp_path)
    inbox = Inbox()
    common = {"authenticator": _auth, "hostname": "127.0.0.1"}
    starttls = Controller(inbox, port=_free_port(), tls_context=server_ctx, require_starttls=True,
                          auth_require_tls=True, **common)  # fmt: skip
    # the whole connection is TLS; aiosmtpd's auth_require_tls only recognises STARTTLS
    implicit = Controller(inbox, port=_free_port(), ssl_context=server_ctx,
                          auth_require_tls=False, **common)  # fmt: skip
    starttls.start()
    implicit.start()
    try:
        yield inbox, ca_file, starttls.port, implicit.port
    finally:
        starttls.stop()
        implicit.stop()


def _configure(s, box, port, security, password=PASSWORD, host="localhost"):
    mail.save_config(s, box, {
        "enabled": True, "host": host, "port": port, "security": security,
        "username": USER, "password": password, "from_address": USER,
        "from_name": "Dr Alex Example", "bcc_self": True,
    })  # fmt: skip


@pytest.mark.parametrize("security", ["starttls", "ssl"])
def test_invoice_arrives_through_a_real_tls_server(
    security, smtp_servers, settings, session, ready, monkeypatch
):
    from test_v1_features import _issued

    inbox, ca_file, starttls_port, ssl_port = smtp_servers
    port = starttls_port if security == "starttls" else ssl_port
    # trust only the throwaway CA, and allow the local test server past the private-address guard
    trusted = ssl.create_default_context(cafile=ca_file)
    monkeypatch.setattr(mail.ssl, "create_default_context", lambda *a, **k: trusted)
    st = replace(settings, webdav_allowlist=WebDavAllowlist.parse("localhost"))
    box = SecretBox(st)
    ready.billing_email = "accounts@example.invalid"
    session.commit()
    inv = _issued(st, session, ready)
    s = db.new_session()
    inv = s.get(Invoice, inv.id)
    _configure(s, box, port, security)

    mail.send_test(s, st, box)
    rcpts, raw = inbox.messages[-1]
    assert rcpts == [USER] and b"Email from Locuvi is working." in raw

    d = mail.draft_for(s, inv)
    mail.send_invoice(s, st, box, inv, to=d["to"], subject=d["subject"], body=d["body"])
    rcpts, raw = inbox.messages[-1]
    assert rcpts == ["accounts@example.invalid", USER]  # practice, plus a copy to the owner
    msg = email.message_from_bytes(raw)
    assert msg["To"] == "accounts@example.invalid" and "Bcc" not in msg
    assert msg["From"] == f"Dr Alex Example <{USER}>"
    assert msg["Date"] and msg["Message-ID"] and "LOC-2026-0001" in msg["Subject"]
    (pdf,) = [p for p in msg.walk() if p.get_filename()]
    assert pdf.get_filename() == "LOC-2026-0001.pdf" and pdf.get_content_type() == "application/pdf"
    assert pdf.get_payload(decode=True) == resolve(st.data_dir, inv.local_pdf_path).read_bytes()

    # wrong app password: a clear error, nothing sent
    before = len(inbox.messages)
    _configure(s, box, port, security, password="wrong-password")
    with pytest.raises(DomainError) as e:
        mail.send_test(s, st, box)
    assert e.value.code == "email.auth_failed" and len(inbox.messages) == before


def test_untrusted_certificate_and_unknown_server_are_reported(
    smtp_servers, settings, session, monkeypatch
):
    inbox, _ca, starttls_port, _ssl = smtp_servers
    st = replace(settings, webdav_allowlist=WebDavAllowlist.parse("localhost"))
    box = SecretBox(st)
    s = db.new_session()
    _configure(s, box, starttls_port, "starttls")
    with pytest.raises(DomainError) as e:  # the test CA isn't trusted: certificates are verified
        mail.send_test(s, st, box)
    assert e.value.code == "email.tls_failed" and inbox.messages == []

    _configure(s, box, starttls_port, "starttls", host="no-such-host.invalid")
    with pytest.raises(DomainError) as e:
        mail.send_test(s, st, box)
    assert e.value.code == "email.unknown_host"
