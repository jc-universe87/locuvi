"""Recently deleted: every delete keeps a restorable copy for 30 days (ADR 0005: undo,
not lose).

A delete stores a JSON snapshot of the deleted row(s) and what depended on them in
``trash_item`` and then deletes as before. Decimals stay decimal strings, dates ISO strings.
Documents and email accounts already soft-delete (``deleted_at``); the bin lists them from
their own tables, so there is one list and one restore path for everything.

Issued invoices and credit notes are never deleted (void only), so they never appear here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date as SADate
from sqlalchemy import DateTime, select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, NotFound
from locuvi.models import (
    Base,
    DecimalString,
    Document,
    Invoice,
    InvoiceEvent,
    InvoiceLine,
    InvoiceStatus,
    MailboxConfig,
    Payment,
    PensionPolicy,
    PensionSubmission,
    Practice,
    SessionStatus,
    TrashItem,
    UTCDateTime,
    WorkSession,
    new_id,
    utcnow,
)
from locuvi.services import core

KEEP_DAYS = 30
KEEP = timedelta(days=KEEP_DAYS)

# Bin ids for rows that soft-delete in their own table.
_DOC = "document:"
_MAIL = "mailbox:"


# ------------------------------------------------------------------ snapshots


def dump(obj: Base) -> dict[str, Any]:
    """Every column of a row as JSON-safe values (Decimal → str, dates → ISO)."""
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:  # type: ignore[attr-defined]
        v = getattr(obj, col.key)
        if isinstance(v, Decimal):
            v = str(v)
        elif isinstance(v, datetime | date):
            v = v.isoformat()
        out[col.key] = v
    return out


def load[T: Base](model: type[T], data: dict[str, Any]) -> T:
    """Rebuild a row from ``dump`` output. Unknown keys are ignored (older snapshots keep
    working after a migration adds columns; missing ones take their defaults)."""
    kw: dict[str, Any] = {}
    for col in model.__table__.columns:  # type: ignore[attr-defined]
        if col.key not in data:
            continue
        v = data[col.key]
        if v is not None:
            t = col.type
            if isinstance(t, DecimalString):
                v = Decimal(str(v))
            elif isinstance(t, UTCDateTime | DateTime):
                v = datetime.fromisoformat(v)
            elif isinstance(t, SADate):
                v = date.fromisoformat(v)
        kw[col.key] = v
    return model(**kw)


def put(
    s: Session,
    kind: str,
    *,
    label: str,
    summary: dict[str, Any],
    payload: dict[str, Any],
) -> TrashItem:
    """Keep a deleted thing for KEEP_DAYS. The caller deletes and commits."""
    item = TrashItem(
        id=new_id(), kind=kind, label=label[:300], summary_json=summary, payload_json=payload
    )
    s.add(item)
    core.audit(s, "trash.deleted", kind=kind, item=item.id)
    return item


# ------------------------------------------------------------- what gets binned


def bin_draft(s: Session, inv: Invoice) -> TrashItem:
    """Snapshot a draft invoice, its lines, history and the diary sessions linked to it."""
    session_ids = list(s.scalars(select(WorkSession.id).where(WorkSession.invoice_id == inv.id)))
    events = list(s.scalars(select(InvoiceEvent).where(InvoiceEvent.invoice_id == inv.id)))
    name = inv.practice.name if inv.practice else ""
    dates = sorted(ln.service_date for ln in inv.lines)
    return put(
        s,
        "invoice",
        label=name,
        summary={
            "practice": name,
            "lines": len(inv.lines),
            "total": str(inv.grand_total) if inv.grand_total is not None else None,
            "first_date": dates[0].isoformat() if dates else None,
            "last_date": dates[-1].isoformat() if dates else None,
        },
        payload={
            "invoice": dump(inv),
            "lines": [dump(ln) for ln in inv.lines],
            "events": [dump(e) for e in events],
            "session_ids": session_ids,
        },
    )


def bin_sessions(s: Session, rows: list[WorkSession]) -> TrashItem | None:
    """One bin entry for sessions deleted together (one session, or an undone series)."""
    if not rows:
        return None
    rows = sorted(rows, key=lambda w: (w.date, w.unit))
    names = sorted({w.practice.name for w in rows if w.practice})
    name = ", ".join(names)
    return put(
        s,
        "sessions",
        label=name,
        summary={
            "count": len(rows),
            "practice": name,
            "date": rows[0].date.isoformat(),
            "last_date": rows[-1].date.isoformat(),
            "unit": rows[0].unit,
        },
        payload={"sessions": [dump(w) for w in rows]},
    )


def bin_payment(s: Session, p: Payment) -> TrashItem:
    inv = p.invoice
    return put(
        s,
        "payment",
        label=inv.invoice_number or "",
        summary={
            "amount": str(p.amount),
            "paid_on": p.paid_on.isoformat(),
            "invoice_number": inv.invoice_number,
            "invoice_id": inv.id,
            "refund": p.amount < 0,
        },
        payload={"payment": dump(p)},
    )


def bin_policy(s: Session, p: PensionPolicy) -> TrashItem:
    return put(
        s,
        "pension_policy",
        label=p.label or "",
        summary={
            "effective_from": p.effective_from.isoformat(),
            "employer_rate": str(p.employer_rate),
            "pensionable_fraction": str(p.pensionable_fraction),
        },
        payload={"policy": dump(p)},
    )


def bin_submission(s: Session, sub: PensionSubmission) -> TrashItem:
    return put(
        s,
        "pension_submission",
        label=sub.month,
        summary={"month": sub.month, "submitted_on": sub.submitted_on.isoformat()},
        payload={"submission": dump(sub)},
    )


# ------------------------------------------------------------------- the list


def _purge_on(deleted_at: datetime) -> str:
    return (deleted_at + KEEP).date().isoformat()


def listing(s: Session) -> list[dict[str, Any]]:
    """Everything in the bin, newest first."""
    out: list[dict[str, Any]] = []
    for t in s.scalars(select(TrashItem)):
        out.append(
            {
                "id": t.id,
                "kind": t.kind,
                "label": t.label,
                "summary": t.summary_json or {},
                "deleted_at": t.deleted_at.isoformat(),
                "purge_on": _purge_on(t.deleted_at),
            }
        )
    for d in s.scalars(select(Document).where(Document.deleted_at.is_not(None))):
        assert d.deleted_at is not None
        out.append(
            {
                "id": f"{_DOC}{d.id}",
                "kind": "document",
                "label": d.title or d.filename or "",
                "summary": {"doc_kind": d.kind, "filename": d.filename},
                "deleted_at": d.deleted_at.isoformat(),
                "purge_on": _purge_on(d.deleted_at),
            }
        )
    for a in s.scalars(select(MailboxConfig).where(MailboxConfig.deleted_at.is_not(None))):
        assert a.deleted_at is not None
        out.append(
            {
                "id": f"{_MAIL}{a.id}",
                "kind": "mailbox",
                "label": a.label or a.username or a.host,
                "summary": {"provider": a.provider or "imap"},
                "deleted_at": a.deleted_at.isoformat(),
                "purge_on": _purge_on(a.deleted_at),
            }
        )
    out.sort(key=lambda x: x["deleted_at"], reverse=True)
    return out


def count(s: Session) -> int:
    return len(listing(s))


# ------------------------------------------------------------------- restore


def restore(s: Session, item_id: str) -> dict[str, Any]:
    """Put a deleted thing back. Returns what was restored (and anything skipped)."""
    if item_id.startswith(_DOC):
        from locuvi.services import documents

        doc = documents.get(s, item_id[len(_DOC) :], include_deleted=True)
        if doc.deleted_at is None:
            raise NotFound("trash.not_found", "That is no longer in Recently deleted.")
        documents.restore(s, doc)
        core.audit(s, "trash.restored", kind="document", item=doc.id)
        s.commit()
        return {"kind": "document", "id": doc.id, "restored": 1, "skipped": 0}
    if item_id.startswith(_MAIL):
        from locuvi.errors import DomainError
        from locuvi.services import mailbox

        try:
            acc_id = int(item_id[len(_MAIL) :])
            acc = mailbox.restore_account(s, acc_id)
        except (ValueError, DomainError) as exc:
            raise NotFound("trash.not_found", "That is no longer in Recently deleted.") from exc
        return {"kind": "mailbox", "id": acc.id, "restored": 1, "skipped": 0}

    item = s.get(TrashItem, item_id)
    if item is None:
        raise NotFound("trash.not_found", "That is no longer in Recently deleted.")
    fn = _RESTORERS.get(item.kind)
    if fn is None:  # pragma: no cover - only kinds written above exist
        raise Conflict("trash.unknown", "This can't be restored.")
    result = fn(s, item.payload_json or {})
    core.audit(s, "trash.restored", kind=item.kind, item=item.id, **{
        k: v for k, v in result.items() if k in {"restored", "skipped"}
    })  # fmt: skip
    s.delete(item)
    s.commit()
    return {"kind": item.kind, **result}


def _restore_invoice(s: Session, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload["invoice"])
    if s.get(Invoice, data["id"]) is not None:
        raise Conflict("trash.exists", "This is already back.")
    if data.get("status") != InvoiceStatus.draft:  # pragma: no cover - only drafts are binned
        raise Conflict("invoice.not_draft", "Only drafts can be restored.")
    if data.get("practice_id") and s.get(Practice, data["practice_id"]) is None:
        data["practice_id"] = None
    if data.get("pension_policy_id") and s.get(PensionPolicy, data["pension_policy_id"]) is None:
        data["pension_policy_id"] = None
    data["invoice_number"] = None
    data["issue_idempotency_key"] = None
    inv = load(Invoice, data)
    inv.lines = [load(InvoiceLine, ln) for ln in payload.get("lines", [])]
    s.add(inv)
    s.flush()
    for e in payload.get("events", []):
        s.add(load(InvoiceEvent, e))
    s.add(InvoiceEvent(invoice_id=inv.id, event_type="restored", metadata_json={}))
    # Only sessions that are still unbilled come back onto the draft.
    linked = skipped = 0
    for sid in payload.get("session_ids", []):
        ws = s.get(WorkSession, sid)
        if ws is not None and ws.invoice_id is None and ws.status == SessionStatus.active:
            ws.invoice_id = inv.id
            linked += 1
        else:
            skipped += 1
    return {"id": inv.id, "restored": 1, "skipped": 0, "sessions_linked": linked,
            "sessions_skipped": skipped}  # fmt: skip


def _restore_sessions(s: Session, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("sessions", [])
    restored = skipped = 0
    first_problem: Conflict | None = None
    for data in rows:
        data = dict(data)
        if s.get(WorkSession, data["id"]) is not None:
            skipped += 1
            continue
        practice = s.get(Practice, data.get("practice_id"))
        if practice is None:
            skipped += 1
            first_problem = first_problem or Conflict(
                "trash.practice_gone", "The practice for this session no longer exists."
            )
            continue
        if data.get("status", SessionStatus.active) == SessionStatus.active:
            clash = s.scalars(
                select(WorkSession).where(
                    WorkSession.practice_id == practice.id,
                    WorkSession.date == date.fromisoformat(data["date"]),
                    WorkSession.unit == data.get("unit"),
                    WorkSession.status == SessionStatus.active,
                )
            ).first()
            if clash is not None:
                skipped += 1
                first_problem = first_problem or Conflict(
                    "trash.session_clash",
                    "There's already a session at that practice then.",
                    practice=practice.name,
                    date=data["date"],
                )
                continue
        # Back onto its draft if that draft still exists; otherwise ready to invoice again.
        inv_id = data.get("invoice_id")
        if inv_id:
            inv = s.get(Invoice, inv_id)
            if inv is None or inv.status != InvoiceStatus.draft:
                data["invoice_id"] = None
        s.add(load(WorkSession, data))
        restored += 1
    if restored == 0 and first_problem is not None:
        raise first_problem
    s.flush()
    return {"restored": restored, "skipped": skipped}


def _restore_payment(s: Session, payload: dict[str, Any]) -> dict[str, Any]:
    from locuvi.services import payments

    data = dict(payload["payment"])
    inv = s.get(Invoice, data.get("invoice_id"))
    if inv is None:
        raise Conflict("trash.invoice_gone", "The invoice for this payment no longer exists.")
    if inv.status != InvoiceStatus.issued:
        raise Conflict(
            "trash.invoice_voided", "That invoice was cancelled, so the payment can't come back."
        )
    if s.get(Payment, data["id"]) is not None:
        raise Conflict("trash.exists", "This is already back.")
    amount = Decimal(str(data["amount"]))
    if amount > 0 and payments.outstanding(inv) < amount:
        raise Conflict(
            "trash.payment_too_much",
            "Adding this payment back would mean the invoice is overpaid.",
            number=inv.invoice_number or "",
        )
    if amount < 0:
        due = Decimal(payments.payment_state(inv).get("refund_due") or "0")
        if due < -amount:
            raise Conflict("trash.refund_not_due", "No refund is owed on this invoice now.")
    p = load(Payment, data)
    inv.payments.append(p)
    s.add(
        InvoiceEvent(
            invoice_id=inv.id,
            event_type="payment_restored",
            metadata_json={"amount": str(amount)},
        )
    )
    s.flush()
    return {"id": inv.id, "restored": 1, "skipped": 0}


def _restore_policy(s: Session, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload["policy"])
    on = date.fromisoformat(data["effective_from"])
    if s.scalars(select(PensionPolicy).where(PensionPolicy.effective_from == on)).first():
        raise Conflict(
            "trash.policy_exists", "There's already a rate starting that day.", date=on.isoformat()
        )
    if s.get(PensionPolicy, data["id"]) is not None:
        raise Conflict("trash.exists", "This is already back.")
    s.add(load(PensionPolicy, data))
    s.flush()
    return {"id": data["id"], "restored": 1, "skipped": 0}


def _restore_submission(s: Session, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload["submission"])
    month = data["month"]
    if s.scalars(select(PensionSubmission).where(PensionSubmission.month == month)).first():
        raise Conflict(
            "trash.month_submitted", "That month is already marked as sent.", month=month
        )
    s.add(load(PensionSubmission, data))
    s.flush()
    return {"id": month, "restored": 1, "skipped": 0}


_RESTORERS = {
    "invoice": _restore_invoice,
    "sessions": _restore_sessions,
    "payment": _restore_payment,
    "pension_policy": _restore_policy,
    "pension_submission": _restore_submission,
}


# ------------------------------------------------------------------- purge


def purge(s: Session, now: datetime | None = None) -> int:
    """Permanently remove bin entries older than KEEP_DAYS (run by the nightly scheduler)."""
    cutoff = (now or utcnow()) - KEEP
    gone = list(s.scalars(select(TrashItem).where(TrashItem.deleted_at < cutoff)))
    for t in gone:
        s.delete(t)
    if gone:
        core.audit(s, "trash.purged", count=len(gone))
        s.commit()
    return len(gone)
