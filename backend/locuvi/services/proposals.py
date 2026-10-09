"""Proposals: suggested diary changes the owner reviews, accepts (in part) or rejects.

Whatever engine produced the raw suggestion (rules or AI), this module re-validates every value,
fills rates from the diary's memory, flags duplicates/clashes against the real diary, and on
acceptance writes through the ordinary diary service. Each proposal is kept as an audit record.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.assistant import rules
from locuvi.assistant.providers import Provider
from locuvi.config import Settings
from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import Document, Practice, Proposal, SessionStatus, WorkSession, utcnow
from locuvi.services import core, diary, documents
from locuvi.services.checks import OVERLAP_UNITS

UNITS = {"am", "pm", "day", "hours"}
TWO_DP = Decimal("0.01")


def _dec(v: Any, *, lo: Decimal, hi: Decimal) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).replace("£", "").replace(",", "").strip())
    except InvalidOperation:
        return None
    if not d.is_finite() or d < lo or d > hi:
        return None
    return d.quantize(TWO_DP)


def _practice_lookup(s: Session) -> tuple[dict[str, Practice], dict[str, Practice]]:
    ps = list(s.scalars(select(Practice).where(Practice.is_archived.is_(False))))
    return {p.id: p for p in ps}, {p.name.strip().lower(): p for p in ps}


def _active_on(s: Session, day: date) -> list[WorkSession]:
    return list(
        s.scalars(
            select(WorkSession).where(
                WorkSession.date == day, WorkSession.status == SessionStatus.active
            )
        )
    )


def clean_item(
    s: Session, raw: dict[str, Any], today: date, default_practice: str | None = None
) -> dict[str, Any] | None:
    """Validate one suggested item and annotate it. Returns None if it is unusable."""
    by_id, by_name = _practice_lookup(s)
    try:
        day = date.fromisoformat(str(raw.get("date", ""))[:10])
    except ValueError:
        return None
    if abs((day - today).days) > 730:
        return None
    unit = str(raw.get("unit") or "day")
    if unit not in UNITS:
        unit = "day"
    action = "cancel" if raw.get("action") == "cancel" else "add"
    hours = _dec(raw.get("hours"), lo=Decimal("0.25"), hi=Decimal("24"))
    if unit == "hours" and hours is None:
        unit = "day"
    rate = _dec(raw.get("rate"), lo=Decimal("0"), hi=Decimal("100000"))

    practice: Practice | None = by_id.get(str(raw.get("practice_id") or ""))
    seen_name = (raw.get("practice_name") or "").strip()[:200] or None
    if practice is None and seen_name:
        practice = by_name.get(seen_name.lower())
    if practice is None and default_practice:
        practice = by_id.get(default_practice)

    flags: list[str] = []
    rate_source = "text" if rate is not None else None
    session_id: str | None = None
    clash_with: str | None = None
    diary_rate: str | None = None
    same_day = _active_on(s, day)
    if practice is None:
        flags.append("needs_practice")
    if action == "add":
        if practice is not None and rate is None:
            rate = diary.remembered_rate(s, practice, unit)
            rate_source = "remembered" if rate is not None else None
        if rate is None:
            flags.append("needs_rate")
        for w in same_day:
            overlaps = w.unit in OVERLAP_UNITS.get(unit, set()) or unit in OVERLAP_UNITS.get(
                w.unit, set()
            )
            if (
                practice is not None
                and w.practice_id == practice.id
                and (w.unit == unit or overlaps)
            ):
                flags.append("duplicate")
                session_id = w.id
                if rate_source == "text" and rate is not None and w.unit == unit and rate != w.rate:
                    flags.append("rate_differs")  # booked, but the email states another fee
                    diary_rate = str(w.rate)
                break
            if overlaps and clash_with is None:
                clash_with = w.practice.name
        if clash_with and "duplicate" not in flags:
            flags.append("clash")
        else:
            clash_with = None
    else:
        match = next(
            (w for w in same_day if (practice is None or w.practice_id == practice.id)
             and (w.unit == unit or unit == "day")),
            None,
        )  # fmt: skip
        if match is None:
            flags.append("not_in_diary")
        else:
            session_id = match.id
            practice = practice or match.practice
            if "needs_practice" in flags:
                flags.remove("needs_practice")
            if diary.is_locked(match, s):
                flags.append("invoiced")

    selectable = not ({"needs_practice", "needs_rate", "not_in_diary", "invoiced"} & set(flags))
    return {
        "date": day.isoformat(),
        "unit": unit,
        "hours": str(hours) if unit == "hours" and hours is not None else None,
        "practice_id": practice.id if practice else None,
        "practice_name": practice.name if practice else seen_name,
        "rate": str(rate) if rate is not None else None,
        "rate_source": rate_source,
        "action": action,
        "note": (str(raw.get("note") or "").strip()[:200] or None),
        "flags": flags,
        "clash_with": clash_with,
        "diary_rate": diary_rate,
        "session_id": session_id,
        "past": day < today,
        "selected": selectable and "duplicate" not in flags,
    }


def build(
    s: Session,
    raw: dict[str, Any],
    *,
    engine: str,
    document: Document | None = None,
    today: date | None = None,
) -> Proposal:
    today = today or core.today_london()
    default_practice = document.practice_id if document is not None else None
    items = []
    for r in (raw.get("items") or [])[:62]:
        if isinstance(r, dict):
            item = clean_item(s, r, today, default_practice)
            if item is not None:
                items.append(item)
    items.sort(key=lambda i: (i["date"], ["am", "pm", "day", "hours"].index(i["unit"])))
    questions = [str(q)[:300] for q in (raw.get("questions") or []) if str(q).strip()][:10]
    prop = Proposal(
        kind="sessions",
        document_id=document.id if document is not None else None,
        engine=engine,
        payload_json={
            "summary": str(raw.get("summary") or "")[:500],
            "items": items,
            "questions": questions,
        },
    )
    if items and all(i["action"] == "add" and i["flags"] == ["duplicate"] for i in items):
        # Everything in it is already in the diary, at the same rate: nothing to decide.
        prop.status = "verified"
        prop.decided_at = utcnow()
        if document is not None:
            document.status = "done"
    s.add(prop)
    core.audit(s, "proposal.created", engine=engine, items=len(items), status=prop.status)
    s.commit()
    return prop


def read_booking(
    s: Session,
    settings: Settings,
    document: Document,
    provider: Provider | None,
    *,
    today: date | None = None,
    send_attachment: bool = False,
) -> Proposal:
    """Turn a document into a proposal with the AI provider if enabled, else the rules.

    Text is minimised before it leaves; a file (scan/photo) is only sent with
    ``send_attachment=True``, i.e. after the owner approved it for this document."""
    today = today or core.today_london()
    if provider is None:
        if not document.text_content.strip():
            raise DomainError(
                "assistant.no_text",
                "There is no readable text in this document. Turn on the assistant to read scans.",
            )
        return build(s, rules.extract(document.text_content, today), engine="rules",
                     document=document, today=today)  # fmt: skip
    attachment = None
    if not document.text_content.strip():
        path = documents.file_path(settings, document)
        if path is None or document.content_type not in {"application/pdf", "image/png",
                                                         "image/jpeg"}:  # fmt: skip
            raise DomainError("assistant.no_text", "There is no readable text in this document.")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise DomainError("document.too_large", "Files up to 10 MB can be read.")
        if not send_attachment:
            # A scan or photo can't be redacted: the owner must approve sending this file.
            raise DomainError(
                "assistant.attachment_consent",
                "This document is a scan or photo. Reading it means sending the file itself to "
                "the AI provider, unredacted. Approve this to continue.",
                document_id=document.id,
            )
        core.audit(s, "assistant.attachment_sent", document_id=document.id,
                   content_type=document.content_type, size=path.stat().st_size)  # fmt: skip
        attachment = (path.read_bytes(), str(document.content_type))
    _, by_name = _practice_lookup(s)
    practices = [{"id": p.id, "name": p.name} for p in by_name.values()]
    raw = provider.read_booking(
        text=document.text_content, attachment=attachment, practices=practices, today=today
    )
    return build(s, raw, engine=provider.engine, document=document, today=today)


def get(s: Session, proposal_id: str) -> Proposal:
    p = s.get(Proposal, proposal_id)
    if p is None:
        raise NotFound("proposal.not_found", "Suggestion not found.")
    return p


def _require_pending(p: Proposal) -> None:
    if p.status != "pending":
        raise Conflict("proposal.decided", "This suggestion has already been handled.")


def accept(
    s: Session, p: Proposal, choices: list[dict[str, Any]], *, today: date | None = None
) -> Proposal:
    """Apply the chosen items (index + optional owner edits). Re-validated before writing."""
    _require_pending(p)
    today = today or core.today_london()
    items: list[dict[str, Any]] = p.payload_json.get("items", [])
    if not choices:
        raise DomainError("proposal.nothing_selected", "Choose at least one session.")
    to_add: list[diary.SessionInput] = []
    cancelled: list[str] = []
    applied: list[int] = []
    for ch in choices:
        idx = ch.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(items) or idx in applied:
            raise DomainError("proposal.bad_item", "That suggestion item does not exist.")
        merged = {**items[idx], **{k: v for k, v in ch.items() if k != "index"}}
        item = clean_item(s, merged, today)
        if item is None:
            raise DomainError("proposal.bad_item", "Check the date of this session.")
        if item["action"] == "cancel":
            if not item["session_id"] or "invoiced" in item["flags"]:
                raise DomainError("proposal.cannot_cancel", "That session cannot be cancelled.")
            ws = diary.get_session_or_404(s, item["session_id"])
            ws.status = SessionStatus.cancelled
            cancelled.append(ws.id)
        else:
            if item["practice_id"] is None:
                raise DomainError("proposal.needs_practice", "Choose the practice first.")
            if item["rate"] is None:
                raise DomainError("session.rate_required", "Enter a rate for this practice once.")
            to_add.append(
                diary.SessionInput(
                    practice_id=item["practice_id"],
                    date=date.fromisoformat(item["date"]),
                    unit=item["unit"],
                    quantity=Decimal(item["hours"]) if item["hours"] else None,
                    rate=Decimal(item["rate"]),
                )
            )
        applied.append(idx)
    try:
        created = diary.add_sessions(s, to_add, commit=False) if to_add else []
    except Exception:
        s.rollback()
        raise
    p.status = "accepted" if len(applied) == len(items) else "partial"
    p.decided_at = utcnow()
    p.result_json = {
        "applied": applied,
        "created": [w.id for w in created],
        "cancelled": cancelled,
    }
    if p.document_id:
        doc = s.get(Document, p.document_id)
        if doc is not None:
            doc.status = "done"
            if doc.practice_id is None and created:
                doc.practice_id = created[0].practice_id
    core.audit(s, "proposal.accepted", proposal_id=p.id, engine=p.engine,
               created=len(created), cancelled=len(cancelled))  # fmt: skip
    s.commit()
    return p


def reject(s: Session, p: Proposal) -> Proposal:
    _require_pending(p)
    p.status = "rejected"
    p.decided_at = utcnow()
    core.audit(s, "proposal.rejected", proposal_id=p.id, engine=p.engine)
    s.commit()
    return p


def undo(s: Session, p: Proposal) -> Proposal:
    """Reverse an acceptance made moments ago (sessions not yet on an invoice)."""
    if p.status not in {"accepted", "partial"} or not p.result_json:
        raise Conflict("proposal.not_accepted", "There is nothing to undo.")
    if p.decided_at and utcnow() - p.decided_at > timedelta(days=1):
        raise Conflict("proposal.too_late", "This can no longer be undone here.")
    rows = [s.get(WorkSession, i) for i in p.result_json.get("created", [])]
    if any(w is not None and w.invoice_id for w in rows):
        raise Conflict("session.invoiced", "This session is on an invoice.")
    for w in rows:
        if w is not None:
            s.delete(w)
    for sid in p.result_json.get("cancelled", []):
        w = s.get(WorkSession, sid)
        if w is not None:
            w.status = SessionStatus.active
    p.status = "pending"
    p.decided_at = None
    p.result_json = None
    if p.document_id and (doc := s.get(Document, p.document_id)) is not None:
        doc.status = "new"
    core.audit(s, "proposal.undone", proposal_id=p.id)
    s.commit()
    return p


def pending(s: Session) -> list[Proposal]:
    return list(
        s.scalars(
            select(Proposal)
            .where(Proposal.status == "pending")
            .order_by(Proposal.created_at.desc())
            .limit(50)
        )
    )


def as_dict(p: Proposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "document_id": p.document_id,
        "status": p.status,
        "engine": p.engine,
        "ai": p.engine.startswith("ai:"),
        "summary": p.payload_json.get("summary", ""),
        "items": p.payload_json.get("items", []),
        "questions": p.payload_json.get("questions", []),
        "result": p.result_json,
        "created_at": p.created_at,
        "decided_at": p.decided_at,
    }
