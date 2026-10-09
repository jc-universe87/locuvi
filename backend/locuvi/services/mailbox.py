"""Read booking emails from mail folders the owner chose (read-only).

Two ways in: IMAP with an app password (Gmail, iCloud, Fastmail, most providers) or a
Microsoft sign-in for Outlook.com, Microsoft 365 and NHSmail (``mail_microsoft``: Graph with
the read-only ``Mail.Read`` permission, because Microsoft no longer accepts IMAP passwords).

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
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from typing import Any

from sqlalchemy.orm import Session

from locuvi.assistant import rules
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import Document, MailboxConfig, MailFolderState, utcnow
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import core, documents, mail_microsoft, proposals
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
    labels = cfg.folder_labels or {}
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider or "imap",
        "ms_client_id": cfg.ms_client_id or "",
        "ms_tenant": cfg.ms_tenant or "common",
        "ms_signed_in": bool(cfg.ms_token_ciphertext),
        "folder_labels": {f: labels.get(f, f) for f in cfg.folders or []},
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
    provider = data.get("provider") or cfg.provider or "imap"
    if provider not in {"imap", "microsoft"}:
        raise DomainError("mailbox.failed", "Unknown email account type.")
    switched = switch_provider(s, cfg, provider)
    host = (data.get("host") or "").strip().lower()
    if host and not re.fullmatch(r"[a-z0-9.-]{1,200}", host):
        raise DomainError("mailbox.bad_host", "Enter the IMAP server name, e.g. imap.example.com.")
    if data.get("security", "ssl") not in {"ssl", "starttls"}:
        raise DomainError("mailbox.bad_security", "Choose SSL/TLS or STARTTLS.")
    folders = [str(f)[:300] for f in (data.get("folders") or []) if str(f).strip()][:20]
    if switched:  # folder names from the previous account don't exist in this one
        folders = []
    elif provider == "microsoft":  # only folders Microsoft listed for this account
        folders = [f for f in folders if f in (cfg.folder_labels or {})]
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
    if cfg.enabled and provider == "microsoft" and not cfg.ms_token_ciphertext:
        raise DomainError("mailbox.ms_signed_out", "Sign in to Microsoft again.")
    if (
        cfg.enabled
        and provider == "imap"
        and not (cfg.host and cfg.username and cfg.password_ciphertext)
    ):
        raise DomainError("mailbox.incomplete", "Fill in server, username and password first.")
    if cfg.enabled and not folders:
        raise DomainError("mailbox.no_folders", "Choose at least one folder to read.")
    for gone in old_folders - set(folders):  # forget progress of folders no longer chosen
        st = s.get(MailFolderState, gone)
        if st is not None:
            s.delete(st)
    core.audit(s, "settings.mailbox_saved", enabled=cfg.enabled, folders=len(folders),
               provider=provider, password_changed=pw is not None)  # fmt: skip
    s.commit()
    return cfg


def switch_provider(s: Session, cfg: MailboxConfig, provider: str) -> bool:
    """Folders of one account mean nothing in another: forget them when the account type changes."""
    if (cfg.provider or "imap") == provider:
        return False
    cfg.provider, cfg.enabled, cfg.folders, cfg.folder_labels = provider, False, [], None
    s.query(MailFolderState).delete()
    return True


def ms_start(client_id: str, tenant: str, transport: Any = None) -> dict[str, Any]:
    return mail_microsoft.start_sign_in(client_id, tenant, transport)


def ms_poll(s: Session, box: SecretBox, transport: Any = None) -> dict[str, Any]:
    cfg = get_config(s)
    before = (cfg.provider or "imap", (cfg.username or "").lower())
    result = mail_microsoft.poll_sign_in(cfg, box, transport)
    if result["status"] == "done":
        if before != ("microsoft", cfg.username.lower()):  # another account: start afresh
            cfg.provider = before[0] if before[0] != "microsoft" else "imap"
            switch_provider(s, cfg, "microsoft")
        core.audit(s, "settings.mailbox_microsoft_signed_in")
        s.commit()
    return result


def ms_sign_out(s: Session) -> MailboxConfig:
    cfg = get_config(s)
    mail_microsoft.sign_out(cfg)
    core.audit(s, "settings.mailbox_microsoft_signed_out")
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
    if cfg.provider == "microsoft":
        graph = mail_microsoft.GraphMail(cfg, box, factory)
        try:
            found = graph.folders()
        finally:
            graph.close()
        cfg.folder_labels = {f["name"]: f["label"] for f in found}
        s.commit()  # also keeps the rotated sign-in token
        return found
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


def _scan_graph_folder(
    s: Session,
    settings: Settings,
    graph: mail_microsoft.GraphMail,
    folder: str,
    since_days: int,
    provider: Any,
    today: date,
    totals: dict[str, int],
) -> None:
    """Like ``_scan_folder`` for Microsoft: progress is the folder's delta link, so messages
    moved into the folder later are read too (their received date may be old)."""
    state = s.get(MailFolderState, folder) or MailFolderState(
        folder=folder, uidvalidity=-1, last_uid=0
    )
    if state.uidvalidity != -1:
        state.uidvalidity, state.last_uid, state.cursor = -1, 0, None
    s.add(state)
    start = today - timedelta(days=since_days)
    since = datetime(start.year, start.month, start.day, tzinfo=UTC)
    try:
        _read_changes(s, settings, graph, state, folder, since, provider, today, totals)
    except DomainError as exc:
        if exc.code != "mailbox.ms_resync" or not state.cursor:
            raise
        state.cursor = None  # Microsoft forgot the position: read again (duplicates skipped)
        _read_changes(s, settings, graph, state, folder, since, provider, today, totals)
    s.commit()


def _read_changes(
    s: Session,
    settings: Settings,
    graph: mail_microsoft.GraphMail,
    state: MailFolderState,
    folder: str,
    since: datetime,
    provider: Any,
    today: date,
    totals: dict[str, int],
) -> None:
    done = 0
    for page, link in graph.changes(folder, state.cursor, since):
        for m in page:
            totals["checked"] += 1
            message_id = str(m.get("internetMessageId") or "").strip()[:300]
            if (
                message_id
                and s.query(Document.id).filter(Document.message_id == message_id).first()
            ):
                totals["already_seen"] += 1
                continue
            raw = graph.mime(str(m.get("id") or ""), MAX_MESSAGE_BYTES) if m.get("id") else None
            if raw:
                _import_message(s, settings, raw, folder, provider, today, totals)
        done += len(page)
        state.cursor = link
        s.commit()
        if done >= MAX_PER_FOLDER:  # the rest next time, from the saved link
            return


def _scan_microsoft(
    s: Session, settings: Settings, box: SecretBox, provider: Any, transport: Any,
    today: date, totals: dict[str, int],
) -> None:  # fmt: skip
    cfg = get_config(s)
    graph = mail_microsoft.GraphMail(cfg, box, transport)
    s.commit()  # keep the rotated sign-in token even if reading fails below
    try:
        for folder in list(cfg.folders or []):
            _scan_graph_folder(s, settings, graph, folder, cfg.since_days, provider, today, totals)
    finally:
        graph.close()


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
        if cfg.provider == "microsoft":
            try:
                _scan_microsoft(s, settings, box, provider, factory, today, totals)
            except DomainError as exc:
                s.rollback()
                cfg = get_config(s)
                cfg.last_error = exc.code
                cfg.last_scan_at = utcnow()
                s.commit()
                raise
            return _finish_scan(s, totals)
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
        return _finish_scan(s, totals)
    finally:
        _scan_lock.release()


def _finish_scan(s: Session, totals: dict[str, int]) -> dict[str, Any]:
    cfg = get_config(s)
    cfg.last_error = None
    cfg.last_scan_at = utcnow()
    cfg.last_result_json = totals
    core.audit(s, "mailbox.scanned", **totals)
    s.commit()
    return totals


def auto_scan_due(cfg: MailboxConfig) -> bool:
    return bool(cfg.enabled and cfg.auto_scan)
