"""Send issued invoices by email over the owner's SMTP account.

Always an explicit owner action. TLS certificates are verified; the SMTP password is
encrypted at rest with the same server key as the WebDAV password and never returned.
"""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any

from sqlalchemy.orm import Session

from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import EmailConfig, Invoice, InvoiceEvent, InvoiceStatus, utcnow
from locuvi.money import fmt_gbp
from locuvi.pdf.render import uk_date
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import branding, core
from locuvi.storage.local import resolve, sha256_file
from locuvi.webdav.urlguard import UrlBlocked, resolve_and_check

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def get_config(s: Session) -> EmailConfig:
    cfg = s.get(EmailConfig, 1)
    if cfg is None:
        cfg = EmailConfig(id=1)
        s.add(cfg)
        s.flush()
    return cfg


def config_public(cfg: EmailConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "host": cfg.host,
        "port": cfg.port,
        "security": cfg.security,
        "username": cfg.username,
        "from_address": cfg.from_address,
        "from_name": cfg.from_name,
        "bcc_self": cfg.bcc_self,
        "password_set": bool(cfg.password_ciphertext),
    }


def valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.match(addr.strip())) and len(addr) <= 200


def save_config(s: Session, box: SecretBox, data: dict[str, Any]) -> EmailConfig:
    cfg = get_config(s)
    host = (data.get("host") or "").strip().lower()
    if host and not re.fullmatch(r"[a-z0-9.-]{1,200}", host):
        raise DomainError("email.bad_host", "Enter the SMTP server name, e.g. smtp.example.com.")
    if data.get("security") not in {"starttls", "ssl"}:
        raise DomainError("email.bad_security", "Choose STARTTLS or SSL/TLS.")
    from_address = (data.get("from_address") or "").strip()
    if from_address and not valid_email(from_address):
        raise DomainError("email.bad_address", "That email address does not look right.")
    pw = data.get("password")
    if pw is not None:
        cfg.password_ciphertext = box.encrypt(pw) if pw else None
    cfg.host = host
    cfg.port = int(data.get("port") or 587)
    cfg.security = data["security"]
    cfg.username = (data.get("username") or "").strip()
    cfg.from_address = from_address
    cfg.from_name = (data.get("from_name") or "").strip()
    cfg.bcc_self = bool(data.get("bcc_self", True))
    cfg.enabled = bool(data.get("enabled"))
    if cfg.enabled and not (cfg.host and cfg.from_address and cfg.password_ciphertext):
        raise DomainError("email.incomplete", "Fill in server, address and password first.")
    core.audit(s, "settings.email_saved", enabled=cfg.enabled, password_changed=pw is not None)
    s.commit()
    return cfg


def draft_for(s: Session, inv: Invoice) -> dict[str, Any]:
    """Pre-filled recipient, subject and message for an issued invoice."""
    snap = inv.immutable_snapshot_json or {}
    seller = snap.get("seller", {}).get("legal_name", "")
    bill = snap.get("bill_to", {})
    to = (inv.practice.billing_email if inv.practice else None) or bill.get("billing_email") or ""
    greeting = (
        f"Dear {bill['contact_name']}," if bill.get("contact_name") else "Dear Practice Manager,"
    )
    body = (
        f"{greeting}\n\n"
        f"Please find attached invoice {inv.invoice_number} for "
        f"{fmt_gbp(inv.grand_total or 0)}, due by {uk_date(inv.due_date)}.\n"
        "Bank details are on the invoice; please quote the invoice number as the reference.\n\n"
        f"{branding.signoff(core.get_profile(s), seller)}"
    )
    return {
        "to": to,
        "subject": f"Invoice {inv.invoice_number} from {seller}".strip(),
        "body": body,
        "configured": bool(get_config(s).enabled),
    }


def send_invoice(
    s: Session,
    settings: Settings,
    box: SecretBox,
    inv: Invoice,
    *,
    to: str,
    subject: str,
    body: str,
    smtp_factory: Any = None,
) -> dict[str, Any]:
    if inv.status != InvoiceStatus.issued:
        raise DomainError("email.not_issued", "Only issued invoices can be sent.")
    cfg = get_config(s)
    if not cfg.enabled:
        raise DomainError("email.not_configured", "Set up email in Settings first.")
    recipients = [a.strip() for a in re.split(r"[,;]", to) if a.strip()]
    if not recipients or len(recipients) > 5 or not all(valid_email(a) for a in recipients):
        raise DomainError("email.bad_address", "Check the recipient email address.")
    path = resolve(settings.data_dir, inv.local_pdf_path or "")
    if not path.is_file() or sha256_file(path) != inv.local_pdf_sha256:
        raise DomainError("invoice.pdf_integrity", "The stored PDF is missing or altered.")

    msg = EmailMessage()
    msg["Date"] = formatdate(localtime=True)  # some mail filters distrust mail without one
    msg["From"] = formataddr((cfg.from_name or "", cfg.from_address))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject.strip()[:200]
    msg["Message-ID"] = make_msgid(domain=cfg.from_address.split("@")[-1])
    msg.set_content(body[:10000])
    msg.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=f"{inv.invoice_number}.pdf",
    )
    bcc = [cfg.from_address] if cfg.bcc_self else []
    _deliver(settings, box, cfg, msg, recipients + bcc, smtp_factory)

    inv.last_emailed_at = utcnow()
    s.add(
        InvoiceEvent(
            invoice_id=inv.id,
            event_type="emailed",
            metadata_json={
                "to": recipients,
                "subject": str(msg["Subject"]),
                "message_id": msg["Message-ID"],
            },
        )
    )
    s.commit()
    return {"sent_to": recipients, "sent_at": inv.last_emailed_at.isoformat()}


def send_to_self(
    s: Session,
    settings: Settings,
    box: SecretBox,
    subject: str,
    body: str,
    smtp_factory: Any = None,
) -> str:
    """Plain email to the owner's own address (digests, notifications). Returns the address."""
    cfg = get_config(s)
    if not cfg.enabled:
        raise DomainError("email.not_configured", "Set up email in Settings first.")
    msg = EmailMessage()
    msg["Date"] = formatdate(localtime=True)  # some mail filters distrust mail without one
    msg["From"] = formataddr((cfg.from_name or "Locuvi", cfg.from_address))
    msg["To"] = cfg.from_address
    msg["Subject"] = subject[:200]
    msg.set_content(body[:20000])
    _deliver(settings, box, cfg, msg, [cfg.from_address], smtp_factory)
    return cfg.from_address


def send_test(s: Session, settings: Settings, box: SecretBox, smtp_factory: Any = None) -> None:
    cfg = get_config(s)
    if not (cfg.host and cfg.from_address and cfg.password_ciphertext):
        raise DomainError("email.incomplete", "Fill in server, address and password first.")
    msg = EmailMessage()
    msg["Date"] = formatdate(localtime=True)  # some mail filters distrust mail without one
    msg["From"] = formataddr((cfg.from_name or "", cfg.from_address))
    msg["To"] = cfg.from_address
    msg["Subject"] = "Locuvi test email"
    msg.set_content("Email from Locuvi is working.")
    _deliver(settings, box, cfg, msg, [cfg.from_address], smtp_factory)


def _deliver(
    settings: Settings,
    box: SecretBox,
    cfg: EmailConfig,
    msg: EmailMessage,
    rcpts: list[str],
    smtp_factory: Any,
) -> None:
    try:
        password = box.decrypt(cfg.password_ciphertext or "")
    except SecretUnavailable:
        raise DomainError("email.password_unreadable", "Re-enter the email password.") from None
    try:
        resolve_and_check(cfg.host, cfg.port, settings)
    except UrlBlocked as exc:
        if exc.reason == "dns":  # usually a typo in the server name
            raise DomainError(
                "email.unknown_host", "Couldn't find that mail server. Check the server name."
            ) from None
        raise DomainError(
            "email.host_blocked", "That mail server address is not allowed."
        ) from None
    ctx = ssl.create_default_context()
    timeout = settings.webdav_timeout_seconds
    try:
        if smtp_factory is not None:
            server = smtp_factory(cfg)
        elif cfg.security == "ssl":
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout, context=ctx)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=timeout)
        with server:
            if cfg.security == "starttls" and smtp_factory is None:
                server.starttls(context=ctx)
            server.login(cfg.username or cfg.from_address, password)
            server.send_message(msg, from_addr=cfg.from_address, to_addrs=rcpts)
    except smtplib.SMTPAuthenticationError:
        raise DomainError("email.auth_failed", "The mail server rejected the login.") from None
    except (ssl.SSLError, ssl.CertificateError):
        raise DomainError(
            "email.tls_failed", "The mail server's certificate could not be verified."
        ) from None
    except (smtplib.SMTPException, OSError):
        raise DomainError(
            "email.send_failed", "The email could not be sent. Check the settings and try again."
        ) from None
