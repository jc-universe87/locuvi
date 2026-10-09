"""Session diary: log work quickly, then turn a practice-month into a draft invoice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import (
    Invoice,
    InvoiceStatus,
    LineUnit,
    Practice,
    SessionStatus,
    WorkSession,
)
from locuvi.money import line_amount
from locuvi.services import core
from locuvi.services import invoices as inv_svc

DEFAULT_DESCRIPTIONS = {
    "am": "GP locum AM session",
    "pm": "GP locum PM session",
    "day": "GP locum full day",
    "hours": "GP locum hours",
    "custom": "GP locum work",
}


@dataclass
class SessionInput:
    practice_id: str
    date: date
    unit: str = LineUnit.am
    quantity: Decimal | None = None
    rate: Decimal | None = None
    pensionable: bool | None = None
    description: str | None = None


def remembered_rate(s: Session, practice: Practice, unit: str) -> Decimal | None:
    """Last rate used for this practice and session type; else the practice's usual rate."""
    last = s.scalars(
        select(WorkSession.rate)
        .where(
            WorkSession.practice_id == practice.id,
            WorkSession.unit == unit,
            WorkSession.status == SessionStatus.active,
        )
        .order_by(WorkSession.date.desc(), WorkSession.created_at.desc())
        .limit(1)
    ).first()
    if last is not None:
        return last
    if unit == LineUnit.hours:
        return practice.hourly_rate
    return practice.default_rate


def _practice(s: Session, practice_id: str) -> Practice:
    p = s.get(Practice, practice_id)
    if p is None:
        raise NotFound("practice.not_found", "Practice not found.")
    return p


def _validate(ws: WorkSession) -> None:
    if ws.unit not in LineUnit.__members__:
        raise DomainError("line.invalid_unit", "Unknown session type.")
    if ws.quantity <= 0 or ws.quantity.as_tuple().exponent < -2:  # type: ignore[operator]
        raise DomainError("line.quantity_positive", "Quantity must be above zero.")
    if ws.rate < 0 or ws.rate.as_tuple().exponent < -2:  # type: ignore[operator]
        raise DomainError("line.price_non_negative", "Rate cannot be negative.")


def add_sessions(
    s: Session, items: list[SessionInput], *, commit: bool = True
) -> list[WorkSession]:
    created = []
    for it in items:
        p = _practice(s, it.practice_id)
        rate = it.rate if it.rate is not None else remembered_rate(s, p, it.unit)
        if rate is None:
            raise DomainError(
                "session.rate_required", "Enter a rate for this practice once.", practice=p.name
            )
        ws = WorkSession(
            practice_id=p.id,
            date=it.date,
            unit=it.unit,
            quantity=it.quantity
            if it.quantity is not None
            else (
                p.default_hours if it.unit == LineUnit.hours and p.default_hours else Decimal("1")
            ),
            rate=rate,
            rate_includes_pension=p.rate_includes_pension,
            pensionable=p.default_pensionable if it.pensionable is None else it.pensionable,
            description=(it.description or "").strip() or DEFAULT_DESCRIPTIONS[it.unit],
            status=SessionStatus.active,
        )
        _validate(ws)
        s.add(ws)
        created.append(ws)
    if commit:
        s.commit()
    else:
        s.flush()
    return created


def get_session_or_404(s: Session, session_id: str) -> WorkSession:
    ws = s.get(WorkSession, session_id)
    if ws is None:
        raise NotFound("session.not_found", "Session not found.")
    return ws


def is_locked(ws: WorkSession, s: Session) -> bool:
    if ws.invoice_id is None:
        return False
    inv = s.get(Invoice, ws.invoice_id)
    return inv is not None and inv.status == InvoiceStatus.issued


def update_session(s: Session, ws: WorkSession, **changes: object) -> WorkSession:
    if is_locked(ws, s):
        raise Conflict("session.invoiced", "This session is on an issued invoice.")
    for k, v in changes.items():
        if v is not None:
            setattr(ws, k, v)
    if "description" in changes and not (ws.description or "").strip():
        ws.description = DEFAULT_DESCRIPTIONS.get(ws.unit, "GP locum work")
    _validate(ws)
    s.commit()
    return ws


def delete_session(s: Session, ws: WorkSession) -> None:
    if is_locked(ws, s):
        raise Conflict("session.invoiced", "This session is on an issued invoice.")
    s.delete(ws)
    s.commit()


def list_sessions(s: Session, start: date, end: date) -> list[WorkSession]:
    return list(
        s.scalars(
            select(WorkSession)
            .where(WorkSession.date >= start, WorkSession.date <= end)
            .order_by(WorkSession.date, WorkSession.unit)
        )
    )


def uninvoiced(s: Session, *, until: date | None = None) -> list[WorkSession]:
    """Worked (dated today or earlier), active sessions not yet on a live invoice."""
    until = until or core.today_london()
    rows = s.scalars(
        select(WorkSession)
        .where(WorkSession.status == SessionStatus.active, WorkSession.date <= until)
        .order_by(WorkSession.date)
    )
    out = []
    for ws in rows:
        if ws.invoice_id is None:
            out.append(ws)
            continue
        inv = s.get(Invoice, ws.invoice_id)
        if inv is None or inv.status == InvoiceStatus.voided:
            out.append(ws)
    return out


def ready_to_invoice(s: Session) -> list[dict[str, object]]:
    """Groups of worked, uninvoiced sessions by practice and calendar month."""
    groups: dict[tuple[str, str], dict[str, object]] = {}
    for ws in uninvoiced(s):
        key = (ws.practice_id, f"{ws.date.year:04d}-{ws.date.month:02d}")
        g = groups.setdefault(
            key,
            {
                "practice_id": ws.practice_id,
                "practice_name": ws.practice.name,
                "month": key[1],
                "sessions": 0,
                "total": Decimal("0.00"),
            },
        )
        g["sessions"] = int(g["sessions"]) + 1  # type: ignore[call-overload]
        g["total"] = g["total"] + line_amount(ws.quantity, ws.rate)  # type: ignore[operator]
    out = sorted(groups.values(), key=lambda g: (str(g["month"]), str(g["practice_name"])))
    for g in out:
        g["total"] = str(g["total"])
    return out


def invoice_month(s: Session, practice_id: str, month: str) -> Invoice:
    """Create a draft invoice from a practice's worked, uninvoiced sessions in a month.

    If a draft already holds sessions for this practice-month, new sessions are added to it.
    """
    try:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
    except ValueError as exc:
        raise DomainError("session.bad_month", "Month must be YYYY-MM.") from exc
    end = date(y + (m == 12), (m % 12) + 1, 1)
    sessions = [
        ws for ws in uninvoiced(s) if ws.practice_id == practice_id and start <= ws.date < end
    ]
    existing_draft = s.scalars(
        select(Invoice)
        .join(WorkSession, WorkSession.invoice_id == Invoice.id)
        .where(
            Invoice.status == InvoiceStatus.draft,
            Invoice.practice_id == practice_id,
            WorkSession.date >= start,
            WorkSession.date < end,
        )
    ).first()
    if not sessions:
        if existing_draft is not None:
            return existing_draft
        raise DomainError("session.nothing_to_invoice", "No worked sessions to invoice.")

    draft = existing_draft
    all_sessions = sorted(
        sessions
        + (
            list(s.scalars(select(WorkSession).where(WorkSession.invoice_id == draft.id)))
            if draft
            else []
        ),
        key=lambda w: (w.date, w.unit),
    )
    lines = [
        inv_svc.LineData(
            w.date,
            w.description,
            w.unit,
            w.quantity,
            w.rate,
            w.pensionable,
            w.rate if w.rate_includes_pension else None,  # converted to the basic fee on save
        )  # fmt: skip
        for w in all_sessions
    ]
    draft = inv_svc.save_draft(s, draft, practice_id=practice_id, lines=lines)
    for w in sessions:
        w.invoice_id = draft.id
    s.commit()
    return draft


def release_sessions(s: Session, invoice_id: str) -> None:
    """Called when a draft is deleted or an invoice is voided: sessions become invoiceable."""
    for ws in s.scalars(select(WorkSession).where(WorkSession.invoice_id == invoice_id)):
        ws.invoice_id = None


def reconcile_on_issue(s: Session, inv: Invoice) -> None:
    """At issue, unlink sessions whose date no longer appears on the invoice's lines."""
    dates = {ln.service_date for ln in inv.lines}
    for ws in s.scalars(select(WorkSession).where(WorkSession.invoice_id == inv.id)):
        if ws.date not in dates:
            ws.invoice_id = None


MAX_SERIES = 120


def series_dates(start: date, until: date, weekdays: list[int], every_weeks: int = 1) -> list[date]:
    """Dates from start to until (inclusive) on the given weekdays (Mon=0), every N weeks."""
    from datetime import timedelta

    if until < start:
        raise DomainError("session.series_range", "The end date is before the start date.")
    if (until - start).days > 400:
        raise DomainError("session.series_range", "Choose up to about a year.")
    days = sorted({d for d in weekdays if 0 <= d <= 6})
    if not days:
        raise DomainError("session.series_weekdays", "Choose at least one weekday.")
    every = max(1, min(every_weeks, 4))
    week0 = start - timedelta(days=start.weekday())
    out = []
    d = start
    while d <= until:
        if d.weekday() in days and ((d - week0).days // 7) % every == 0:
            out.append(d)
        d += timedelta(days=1)
    if len(out) > MAX_SERIES:
        raise DomainError("session.series_too_long", "That's too many sessions at once.")
    return out


def add_series(
    s: Session, base: SessionInput, dates: list[date], *, dry_run: bool = False
) -> dict[str, object]:
    """Repeating booking: one session per date, skipping days already booked at this practice."""
    _practice(s, base.practice_id)
    taken = {
        (w.date, w.unit)
        for w in s.scalars(
            select(WorkSession).where(
                WorkSession.practice_id == base.practice_id,
                WorkSession.status == SessionStatus.active,
                WorkSession.date.in_(dates),
            )
        )
    }
    overlap = {"am": {"am", "day"}, "pm": {"pm", "day"}, "day": {"am", "pm", "day"}}
    new_dates, skipped = [], []
    for d in dates:
        clash = any((d, u) in taken for u in overlap.get(base.unit, {base.unit}))
        (skipped if clash else new_dates).append(d)
    if dry_run:
        return {"dates": [d.isoformat() for d in new_dates],
                "skipped": [d.isoformat() for d in skipped]}  # fmt: skip
    items = [
        SessionInput(
            base.practice_id,
            d,
            base.unit,
            base.quantity,
            base.rate,
            base.pensionable,
            base.description,
        )  # fmt: skip
        for d in new_dates
    ]
    created = add_sessions(s, items) if items else []
    core.audit(s, "diary.series_added", sessions=len(created), skipped=len(skipped))
    s.commit()
    return {"created": created, "skipped": [d.isoformat() for d in skipped]}


def delete_many(s: Session, ids: list[str]) -> int:
    """Undo for a series: removes the given sessions unless they are on an issued invoice."""
    n = 0
    for i in ids[:MAX_SERIES]:
        ws = s.get(WorkSession, i)
        if ws is not None and not is_locked(ws, s):
            if ws.invoice_id is None:
                s.delete(ws)
                n += 1
    s.commit()
    return n
