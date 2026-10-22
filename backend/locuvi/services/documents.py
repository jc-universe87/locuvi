"""Document inbox: keep booking emails, remittances and forms next to the records they explain.

Files are stored under ``data_dir/documents`` with a random name (never the user's filename).
Text is extracted once on arrival so documents can be searched and read by the assistant.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import io
import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import DomainError, NotFound
from locuvi.models import Document, Practice, utcnow
from locuvi.services import core

log = logging.getLogger(__name__)

MAX_BYTES = 15 * 1024 * 1024
MAX_TEXT = 200_000
KINDS = ("booking", "remittance", "statement", "pension", "other")
TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "message/rfc822": ".eml",
}
EXT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".eml": "message/rfc822",
}
TRASH_DAYS = 30

_BOOKING = re.compile(r"\b(locum|session|booking|confirm|am\b|pm\b|surgery)", re.I)
_REMIT = re.compile(r"\b(remittance|payment advice|bacs|paid)\b", re.I)
_PENSION = re.compile(r"\b(locum a|locum b|form a|form b|pensionable|pcse)\b", re.I)


def doc_dir(settings: Settings) -> Path:
    return Path(settings.data_dir) / "documents"


def _sniff_type(filename: str, declared: str | None, head: bytes) -> str:
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    ext = Path(filename).suffix.lower()
    guess = EXT_TYPES.get(ext) or (declared or "").split(";")[0].strip().lower()
    if guess in {"application/pdf", "image/png", "image/jpeg"}:
        # declared binary type but the bytes don't match: refuse rather than mislabel
        raise DomainError("document.unsupported", "That file type is not supported.")
    if guess in TYPES:
        return guess
    raise DomainError("document.unsupported", "That file type is not supported.")


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_text(data: bytes, content_type: str) -> str:
    """Best-effort plain text. Never raises: an unreadable file is still kept."""
    try:
        if content_type == "application/pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:30])
        elif content_type == "message/rfc822":
            text = email_text(email.message_from_bytes(data, policy=email.policy.default))
        elif content_type.startswith("text/"):
            text = _decode(data)
        else:
            text = ""
    except Exception:  # noqa: BLE001 - malformed files are common; keep the file anyway
        log.info("document text extraction failed (%s)", content_type)
        text = ""
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    return text[:MAX_TEXT]


def email_text(msg: email.message.EmailMessage) -> str:
    """Headers, body (plain preferred) and the text of PDF/text attachments."""
    body = msg.get_body(preferencelist=("plain", "html"))
    content = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        content = re.sub(r"<[^>]+>", " ", content)
    parts = [
        f"From: {msg.get('from', '')}\nDate: {msg.get('date', '')}\n"
        f"Subject: {msg.get('subject', '')}\n\n{content}"
    ]
    for att in list(msg.iter_attachments())[:5]:
        ctype = att.get_content_type()
        if ctype in {"application/pdf", "text/plain", "text/csv"}:
            payload = att.get_payload(decode=True) or b""
            if len(payload) <= MAX_BYTES:
                extracted = extract_text(payload, ctype)
                if extracted:
                    parts.append(f"--- Attachment: {att.get_filename() or ctype} ---\n{extracted}")
    return "\n\n".join(parts)


def guess_kind(text: str, filename: str = "") -> str:
    hay = f"{filename}\n{text[:4000]}"
    if _PENSION.search(hay):
        return "pension"
    if _REMIT.search(hay):
        return "remittance"
    if _BOOKING.search(hay):
        return "booking"
    return "other"


def guess_practice(s: Session, text: str) -> str | None:
    """A practice whose name appears in the text (longest name wins)."""
    hay = text[:20000].lower()
    best: Practice | None = None
    for p in s.scalars(select(Practice).where(Practice.is_archived.is_(False))):
        name = p.name.strip().lower()
        if len(name) >= 4 and name in hay and (best is None or len(name) > len(best.name)):
            best = p
    return best.id if best else None


def guess_invoice(s: Session, text: str) -> str | None:
    """The issued invoice whose number appears in the text (only when exactly one does)."""
    from locuvi.models import Invoice

    hay = re.sub(r"[^a-z0-9]", "", text[:50000].lower())
    if not hay:
        return None
    hits = [
        i.id
        for i in s.scalars(select(Invoice).where(Invoice.invoice_number.is_not(None)))
        if len(re.sub(r"[^a-z0-9]", "", (i.invoice_number or "").lower())) >= 4
        and re.sub(r"[^a-z0-9]", "", (i.invoice_number or "").lower()) in hay
    ]
    return hits[0] if len(hits) == 1 else None


def _title_from(text: str, fallback: str) -> str:
    m = re.search(r"^Subject:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip()[:200]
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 4:
            return line[:80]
    return fallback[:200]


def add_upload(
    s: Session, settings: Settings, filename: str, declared_type: str | None, data: bytes
) -> Document:
    if not data:
        raise DomainError("document.empty", "That file is empty.")
    if len(data) > MAX_BYTES:
        raise DomainError("document.too_large", "Files up to 15 MB can be added.")
    filename = Path(filename or "document").name[:200] or "document"
    ctype = _sniff_type(filename, declared_type, data[:16])
    digest = hashlib.sha256(data).hexdigest()
    existing = s.scalars(
        select(Document).where(Document.sha256 == digest, Document.deleted_at.is_(None))
    ).first()
    if existing is not None:
        return existing  # the same file twice is one document
    stored = f"{uuid.uuid4().hex}{TYPES[ctype]}"
    folder = doc_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{stored}.part"
    tmp.write_bytes(data)
    tmp.replace(folder / stored)
    text = extract_text(data, ctype)
    doc = Document(
        kind=guess_kind(text, filename),
        title=_title_from(text, Path(filename).stem) if ctype == "message/rfc822" else filename,
        source="upload",
        filename=filename,
        content_type=ctype,
        size=len(data),
        sha256=digest,
        stored_name=stored,
        text_content=text,
        practice_id=guess_practice(s, text),
        invoice_id=guess_invoice(s, text),
    )
    db.end_read(s)  # reading the file took a while; another write may have landed meanwhile
    s.add(doc)
    core.audit(s, "document.added", source="upload", content_type=ctype, size=len(data))
    s.commit()
    return doc


def add_paste(s: Session, text: str, kind: str | None = None) -> Document:
    text = (text or "").strip()
    if not text:
        raise DomainError("document.empty", "Paste some text first.")
    text = text[:MAX_TEXT]
    doc = Document(
        kind=kind if kind in KINDS else guess_kind(text),
        title=_title_from(text, "Pasted text"),
        source="paste",
        content_type="text/plain",
        size=len(text.encode("utf-8")),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text_content=text,
        practice_id=guess_practice(s, text),
        invoice_id=guess_invoice(s, text),
    )
    s.add(doc)
    core.audit(s, "document.added", source="paste", size=doc.size)
    s.commit()
    return doc


def get(s: Session, doc_id: str, *, include_deleted: bool = False) -> Document:
    doc = s.get(Document, doc_id)
    if doc is None or (doc.deleted_at is not None and not include_deleted):
        raise NotFound("document.not_found", "Document not found.")
    return doc


def file_path(settings: Settings, doc: Document) -> Path | None:
    if not doc.stored_name:
        return None
    p = doc_dir(settings) / doc.stored_name
    return p if p.is_file() else None


def list_docs(s: Session, *, status: str | None = None, q: str | None = None) -> list[Document]:
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Document.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Document.title.ilike(like) | Document.text_content.ilike(like))
    return list(s.scalars(stmt.order_by(Document.created_at.desc()).limit(500)))


def update(s: Session, doc: Document, **changes: object) -> Document:
    if "kind" in changes and changes["kind"] not in KINDS:
        raise DomainError("document.bad_kind", "Unknown document type.")
    if changes.get("practice_id"):
        if s.get(Practice, str(changes["practice_id"])) is None:
            raise NotFound("practice.not_found", "Practice not found.")
    if changes.get("invoice_id"):
        from locuvi.models import Invoice

        if s.get(Invoice, str(changes["invoice_id"])) is None:
            raise NotFound("invoice.not_found", "Invoice not found.")
    for k, v in changes.items():
        setattr(doc, k, (v or None) if k in {"practice_id", "invoice_id"} else v)
    s.commit()
    return doc


def trash(s: Session, doc: Document) -> None:
    doc.deleted_at = utcnow()
    core.audit(s, "document.deleted", document_id=doc.id)
    s.commit()


def batch(s: Session, ids: list[str], action: str) -> list[str]:
    """Mark several items dealt with / back to do, delete them (to Recently deleted) or put
    them back, in one go. Returns the ids actually changed, so the owner can undo."""
    wanted = list(dict.fromkeys(ids))
    rows = s.scalars(select(Document).where(Document.id.in_(wanted)))
    changed: list[str] = []
    now = utcnow()
    for doc in rows:
        if action == "restore":
            if doc.deleted_at is None:
                continue
            doc.deleted_at = None
        elif doc.deleted_at is not None:
            continue  # binned items only come back through restore
        elif action == "delete":
            doc.deleted_at = now
        elif doc.status != action:  # "done" | "new"
            doc.status = action
        else:
            continue
        changed.append(doc.id)
    if changed:
        core.audit(s, f"document.batch_{action}", count=len(changed))
    s.commit()
    return changed


def restore(s: Session, doc: Document) -> Document:
    doc.deleted_at = None
    s.commit()
    return doc


def purge_trash(s: Session, settings: Settings) -> int:
    """Permanently remove documents deleted more than TRASH_DAYS ago (and their files)."""
    cutoff = utcnow() - timedelta(days=TRASH_DAYS)
    gone = list(
        s.scalars(
            select(Document).where(Document.deleted_at.is_not(None), Document.deleted_at < cutoff)
        )
    )
    from locuvi.models import Proposal

    for doc in gone:
        p = file_path(settings, doc)
        if p is not None:
            p.unlink(missing_ok=True)
        for prop in s.scalars(select(Proposal).where(Proposal.document_id == doc.id)):
            prop.document_id = None  # keep the audit record, drop the link
        s.delete(doc)
    if gone:
        s.commit()
    return len(gone)


def new_count(s: Session) -> int:
    return len(
        list(
            s.scalars(
                select(Document.id).where(Document.status == "new", Document.deleted_at.is_(None))
            )
        )
    )


def for_invoice(s: Session, invoice_id: str) -> list[Document]:
    return list(
        s.scalars(
            select(Document)
            .where(Document.invoice_id == invoice_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at)
        )
    )


def correspondence(s: Session, invoice_id: str) -> list[dict[str, object]]:
    """Emails sent from Locuvi about the invoice, and inbox documents linked to it, by date."""
    from locuvi.models import InvoiceEvent

    out: list[dict[str, object]] = []
    for e in s.scalars(
        select(InvoiceEvent).where(
            InvoiceEvent.invoice_id == invoice_id, InvoiceEvent.event_type == "emailed"
        )
    ):
        md = e.metadata_json or {}
        out.append({"type": "sent", "at": e.timestamp.isoformat(), "to": md.get("to", []),
                    "subject": md.get("subject")})  # fmt: skip
    for d in for_invoice(s, invoice_id):
        out.append({"type": "document", "id": d.id, "at": d.created_at.isoformat(),
                    "title": d.title, "kind": d.kind, "source": d.source})  # fmt: skip
    return sorted(out, key=lambda x: str(x["at"]))
