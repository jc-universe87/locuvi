"""Read booking emails from mail folders the owner chose (IMAP, read-only).

Rules that keep this safe:
- Only the folders the owner ticked are opened, never the whole mailbox.
- Folders are opened read-only (EXAMINE) and messages fetched with BODY.PEEK, so nothing is
  marked read, moved, flagged or deleted. No IMAP write command is ever sent.
- Only emails that look like bookings or remittances are kept (as inbox documents); everything
  else is skipped and not stored.
- Bookings are read into *proposals* checked against the Diary ("already booked", "rate
  differs", "clashes"…). Nothing becomes a diary entry until the owner accepts it.
- TLS certificates are verified; the server address goes through the same private-address
  guard as WebDAV/SMTP; the password is encrypted at rest and never returned.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import ssl
import threading
from datetime import date, timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy.orm import Session

from locuvi.assistant import rules
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import Document, MailboxConfig, MailFolderState, utcnow
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import core, documents, proposals
from locuvi.webdav.urlguard import UrlBlocked, resolve_and_check

log = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 10 * 1024 * 1024
MAX_PER_FOLDER = 200  # per scan; the rest is picked up next time
_scan_lock = threading.Lock()

_BOOKING_WORDS = re.compile(
    r"\b(locum|sessions?|booking|booked|cover|rota|shift|surgery|clinic)\b", re.I
)
_REMITTANCE_WORDS = re.compile(r"\b(remittance|payment advice|bacs|paid)\b", re.I)


# ----------------------------------------------------------------------- config


def get_config(s: Session) -> MailboxConfig:
    cfg = s.get(MailboxConfig, 1)
    if cfg is None:
        cfg = MailboxConfig(id=1, folders=[])
        s.add(cfg)
        s.flush()
    return cfg


def config_public(cfg: MailboxConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "host": cfg.host,
        "port": cfg.port,
        "security": cfg.security,
        "username": cfg.username,
        "password_set": bool(cfg.password_ciphertext),
        "folders": list(cfg.folders or []),
        "since_days": cfg.since_days,
        "auto_scan": cfg.auto_scan,
        "last_scan_at": cfg.last_scan_at,
        "last_error": cfg.last_error,
        "last_result": cfg.last_result_json,
    }


def save_config(s: Session, box: SecretBox, data: dict[str, Any]) -> MailboxConfig:
    cfg = get_config(s)
    host = (data.get("host") or "").strip().lower()
    if host and not re.fullmatch(r"[a-z0-9.-]{1,200}", host):
        raise DomainError("mailbox.bad_host", "Enter the IMAP server name, e.g. imap.example.com.")
    if data.get("security", "ssl") not in {"ssl", "starttls"}:
        raise DomainError("mailbox.bad_security", "Choose SSL/TLS or STARTTLS.")
    folders = [str(f)[:300] for f in (data.get("folders") or []) if str(f).strip()][:20]
    pw = data.get("password")
    if pw is not None:
        cfg.password_ciphertext = box.encrypt(pw) if pw else None
    old_folders = set(cfg.folders or [])
    cfg.host = host
    cfg.port = int(data.get("port") or 993)
    cfg.security = data.get("security", "ssl")
    cfg.username = (data.get("username") or "").strip()[:200]
    cfg.folders = folders
    cfg.since_days = max(1, min(int(data.get("since_days") or 90), 730))
    cfg.auto_scan = bool(data.get("auto_scan", True))
    cfg.enabled = bool(data.get("enabled"))
    if cfg.enabled and not (cfg.host and cfg.username and cfg.password_ciphertext):
        raise DomainError("mailbox.incomplete", "Fill in server, username and password first.")
    if cfg.enabled and not folders:
        raise DomainError("mailbox.no_folders", "Choose at least one folder to read.")
    for gone in old_folders - set(folders):  # forget progress of folders no longer chosen
        st = s.get(MailFolderState, gone)
        if st is not None:
            s.delete(st)
    core.audit(s, "settings.mailbox_saved", enabled=cfg.enabled, folders=len(folders),
               password_changed=pw is not None)  # fmt: skip
    s.commit()
    return cfg


# ------------------------------------------------------------------ connection


def _password(cfg: MailboxConfig, box: SecretBox) -> str:
    try:
        return box.decrypt(cfg.password_ciphertext or "")
    except SecretUnavailable:
        raise DomainError("mailbox.password_unreadable", "Re-enter the email password.") from None


def connect(cfg: MailboxConfig, box: SecretBox, settings: Settings, factory: Any = None) -> Any:
    """Logged-in IMAP connection. ``factory(cfg)`` lets tests supply a fake server."""
    if not (cfg.host and cfg.username and cfg.password_ciphertext):
        raise DomainError("mailbox.incomplete", "Fill in server, username and password first.")
    password = _password(cfg, box)
    try:
        if factory is not None:
            conn = factory(cfg)
        else:
            resolve_and_check(cfg.host, cfg.port, settings)
            ctx = ssl.create_default_context()
            timeout = settings.webdav_timeout_seconds
            if cfg.security == "ssl":
                conn = imaplib.IMAP4_SSL(cfg.host, cfg.port, ssl_context=ctx, timeout=timeout)
            else:
                conn = imaplib.IMAP4(cfg.host, cfg.port, timeout=timeout)
                conn.starttls(ssl_context=ctx)
        conn.login(cfg.username, password)
        return conn
    except UrlBlocked:
        raise DomainError(
            "mailbox.host_blocked", "That mail server address is not allowed."
        ) from None
    except (ssl.SSLError, ssl.CertificateError):
        raise DomainError(
            "mailbox.tls_failed", "The mail server's certificate could not be verified."
        ) from None
    except imaplib.IMAP4.error:
        raise DomainError("mailbox.auth_failed", "The mail server rejected the login.") from None
    except OSError:
        raise DomainError("mailbox.unreachable", "Could not reach the mail server.") from None


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$')


def _parse_list_line(raw: bytes | str) -> tuple[str, bool] | None:
    line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    m = _LIST_RE.match(line.strip())
    if not m:
        return None
    name = m["name"].strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    selectable = "\\noselect" not in m["flags"].lower()
    return name, selectable


def decode_folder(name: str) -> str:
    """IMAP modified UTF-7 → readable name (for display only; the raw name is used to select)."""

    def _dec(m: re.Match[str]) -> str:
        chunk = m.group(1)
        if chunk == "":
            return "&"
        b64 = chunk.replace(",", "/")
        b64 += "=" * (-len(b64) % 4)
        try:
            import base64

            return base64.b64decode(b64).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return m.group(0)

    return re.sub(r"&([^-]*)-", _dec, name)


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def list_folders(
    s: Session, settings: Settings, box: SecretBox, factory: Any = None
) -> list[dict[str, str]]:
    cfg = get_config(s)
    conn = connect(cfg, box, settings, factory)
    try:
        typ, data = conn.list()
        if typ != "OK":
            raise DomainError("mailbox.failed", "Could not list the mail folders.")
        out = []
        for raw in data or []:
            parsed = _parse_list_line(raw) if raw else None
            if parsed and parsed[1]:
                out.append({"name": parsed[0], "label": decode_folder(parsed[0])})
        return sorted(out, key=lambda f: (f["label"].upper() != "INBOX", f["label"].lower()))
    finally:
        _logout(conn)


def _logout(conn: Any) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 - best effort
        pass


# ------------------------------------------------------------------------- scan


def classify(text: str, today: date) -> str | None:
    """'booking', 'remittance' or None (not kept). Bookings need a date and a booking word."""
    head = text[:20000]
    if _BOOKING_WORDS.search(head) and rules.find_dates(head, today):
        return "booking"
    if _REMITTANCE_WORDS.search(head):
        return "remittance"
    return None


def _uidvalidity(conn: Any) -> int:
    try:
        _, data = conn.response("UIDVALIDITY")
        return int(data[0]) if data and data[0] else 0
    except (ValueError, TypeError, IndexError):
        return 0


def _fetch_bytes(data: Any) -> bytes | None:
    for part in data or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes | bytearray):
            return bytes(part[1])
    return None


def _size_of(data: Any) -> int:
    for part in data or []:
        raw = part[0] if isinstance(part, tuple) else part
        if isinstance(raw, bytes | bytearray):
            m = re.search(rb"RFC822\.SIZE (\d+)", raw)
            if m:
                return int(m.group(1))
    return 0


def _scan_folder(
    s: Session,
    settings: Settings,
    conn: Any,
    folder: str,
    since_days: int,
    provider: Any,
    today: date,
    totals: dict[str, int],
) -> None:
    typ, _ = conn.select(_quote(folder), readonly=True)  # EXAMINE: never changes flags
    if typ != "OK":
        totals["folder_errors"] += 1
        return
    validity = _uidvalidity(conn)
    state = s.get(MailFolderState, folder) or MailFolderState(folder=folder, uidvalidity=0)
    if state.uidvalidity != validity:
        state.uidvalidity, state.last_uid = validity, 0
        s.add(state)
    if state.last_uid:
        criteria = ("UID", f"{state.last_uid + 1}:*")
    else:
        since = (today - timedelta(days=since_days)).strftime("%d-%b-%Y")
        criteria = ("SINCE", since)
    typ, data = conn.uid("SEARCH", None, *criteria)
    if typ != "OK":
        totals["folder_errors"] += 1
        return
    uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > state.last_uid)
    for uid in uids[:MAX_PER_FOLDER]:
        totals["checked"] += 1
        typ, meta = conn.uid("FETCH", str(uid), "(RFC822.SIZE)")
        if typ != "OK" or _size_of(meta) > MAX_MESSAGE_BYTES:
            state.last_uid = uid
            continue
        typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")  # PEEK: stays unread
        raw = _fetch_bytes(data) if typ == "OK" else None
        state.last_uid = uid
        if not raw:
            continue
        _import_message(s, settings, raw, folder, provider, today, totals)
    s.commit()


def _import_message(
    s: Session,
    settings: Settings,
    raw: bytes,
    folder: str,
    provider: Any,
    today: date,
    totals: dict[str, int],
) -> None:
    msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[assignment]
    message_id = str(msg.get("message-id", "") or "").strip()[:300] or None
    if message_id and s.query(Document.id).filter(Document.message_id == message_id).first():
        totals["already_seen"] += 1
        return
    text = documents.email_text(msg)
    kind = classify(text, today)
    if kind is None:
        totals["skipped"] += 1
        return
    subject = str(msg.get("subject", "") or "").strip() or "Email"
    safe = re.sub(r"[^\w .-]+", "", subject)[:80].strip() or "email"
    doc = documents.add_upload(s, settings, f"{safe}.eml", "message/rfc822", raw)
    doc.source, doc.kind = "email", kind
    doc.message_id, doc.mail_folder = message_id, folder
    s.commit()
    totals[kind + "s"] += 1
    if kind != "booking":
        return
    try:
        prop = proposals.read_booking(s, settings, doc, provider, today=today)
    except DomainError as exc:
        log.info("booking email kept but not read: %s", exc.code)
        totals["unread"] += 1
        return
    if prop.status == "verified":
        totals["already_booked"] += 1
    elif prop.payload_json.get("items"):
        totals["to_review"] += 1


def scan(
    s: Session,
    settings: Settings,
    box: SecretBox,
    *,
    provider: Any = None,
    factory: Any = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Read new messages in the chosen folders. Safe to call repeatedly (resumes by UID)."""
    cfg = get_config(s)
    if not cfg.enabled:
        raise DomainError("mailbox.not_configured", "Set up email folders in Settings first.")
    if not _scan_lock.acquire(blocking=False):
        raise DomainError("mailbox.busy", "Already checking your email.")
    today = today or core.today_london()
    totals = {k: 0 for k in ("checked", "skipped", "already_seen", "bookings", "remittances",
                             "already_booked", "to_review", "unread", "folder_errors")}  # fmt: skip
    try:
        try:
            conn = connect(cfg, box, settings, factory)
        except DomainError as exc:
            cfg.last_error = exc.code
            cfg.last_scan_at = utcnow()
            s.commit()
            raise
        try:
            for folder in cfg.folders or []:
                _scan_folder(s, settings, conn, folder, cfg.since_days, provider, today, totals)
        except (imaplib.IMAP4.error, OSError):
            s.rollback()
            cfg = get_config(s)
            cfg.last_error = "mailbox.failed"
            cfg.last_scan_at = utcnow()
            s.commit()
            raise DomainError("mailbox.failed", "Reading the mail folders failed.") from None
        finally:
            _logout(conn)
        cfg = get_config(s)
        cfg.last_error = None
        cfg.last_scan_at = utcnow()
        cfg.last_result_json = totals
        core.audit(s, "mailbox.scanned", **totals)
        s.commit()
        return totals
    finally:
        _scan_lock.release()


def auto_scan_due(cfg: MailboxConfig) -> bool:
    return bool(cfg.enabled and cfg.auto_scan)
