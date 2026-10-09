"""NHS pension figures for GP Locum Forms A and B, built from issued invoices and payments.

Two ledgers (NHSBSA GP locum guidance):
- **Form A** — one per engagement (invoice), for the month the work was done, signed by the
  practice. Work that ended more than 10 weeks ago can no longer be pensioned.
- **Form B** — monthly summary of pensionable income *received* in that month (from recorded
  payments, apportioned per invoice), due with contributions by the 7th of the next month.
Figures are net of credit notes. Locuvi prepares figures to copy; it never submits anything.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError
from locuvi.models import FormARecord, Invoice, InvoiceStatus, PcseRecord, PensionSubmission
from locuvi.money import ZERO, round_money
from locuvi.services import core

TEN_WEEKS = 70  # days: freelance locum work that ended longer ago can no longer be pensioned


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def form_b_due(month: str) -> date:
    """Form B and contributions must reach NHS Pensions/PCSE by the 7th of the next month."""
    y, m = (int(x) for x in month.split("-"))
    return date(y + (m == 12), m % 12 + 1, 7)


def _pension_invoices(s: Session) -> list[Invoice]:
    out = []
    for inv in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued)):
        if inv.pension_enabled and inv.pensionable_pay and any(ln.pensionable for ln in inv.lines):
            out.append(inv)
    return out


def work_month(inv: Invoice) -> str:
    """The Form A month: when the pensionable work was done (invoices are one month).

    For an invoice without pensionable lines, the month of its first line."""
    dates = [ln.service_date for ln in inv.lines if ln.pensionable] or [
        ln.service_date for ln in inv.lines
    ]
    return _ym(min(dates)) if dates else ""


def last_session(inv: Invoice) -> date:
    return max(ln.service_date for ln in inv.lines if ln.pensionable)


def net_figures(inv: Invoice) -> dict[str, Decimal]:
    """Invoice figures after credit notes."""
    credits = list(inv.credit_notes)

    def net(field: str) -> Decimal:
        return round_money(
            (getattr(inv, field) or ZERO) - sum((getattr(c, field) for c in credits), ZERO)
        )

    return {
        "total": net("grand_total"),
        "fees": net("pensionable_basic_total"),
        "pay": net("pensionable_pay"),
        "employer": net("employer_contribution"),
    }


def receipts(inv: Invoice) -> list[dict[str, Any]]:
    """Each payment's share of the invoice's pensionable pay and employer contribution.

    Shares are cumulative (rounded at each step), so a fully paid invoice's receipts add up
    exactly to its figures however it was paid. Refunds (negative payments) take shares back.
    """
    net = net_figures(inv)
    total = net["total"]
    out: list[dict[str, Any]] = []
    if total <= 0:
        return out
    paid_before = ZERO
    taken = {"pay": ZERO, "employer": ZERO, "fees": ZERO}
    for p in sorted(inv.payments, key=lambda p: (p.paid_on, p.created_at)):
        paid_after = paid_before + p.amount
        share = min(max(paid_after / total, Decimal(0)), Decimal(1))
        part = {}
        for k in ("pay", "employer", "fees"):
            upto = round_money(net[k] * share)
            part[k], taken[k] = upto - taken[k], upto
        paid_before = paid_after
        out.append({
            "payment_id": p.id,
            "invoice_id": inv.id,
            "invoice_number": inv.invoice_number,
            "practice": (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", ""),
            "work_month": work_month(inv),
            "paid_on": p.paid_on.isoformat(),
            "received_month": _ym(p.paid_on),
            "amount": str(p.amount),
            "fees": str(part["fees"]),
            "pensionable_pay": str(part["pay"]),
            "employer": str(part["employer"]),
        })  # fmt: skip
    return out


def _forms_a(s: Session, month: str, invoices: list[Invoice]) -> list[dict[str, Any]]:
    """Form A: one per engagement (invoice) for work done in ``month``."""
    records = {
        r.practice_key: r for r in s.scalars(select(FormARecord).where(FormARecord.month == month))
    }
    rows = []
    for inv in sorted(invoices, key=lambda i: i.invoice_number or ""):
        if work_month(inv) != month:
            continue
        net = net_figures(inv)
        credits = list(inv.credit_notes)
        credited_lines = {i for c in credits for i in c.line_ids}
        received = sum((Decimal(r["pensionable_pay"]) for r in receipts(inv)), ZERO)
        bill = (inv.immutable_snapshot_json or {}).get("bill_to", {})
        rec = records.get(inv.id)
        rows.append({
            "key": inv.id,
            "invoice_id": inv.id,
            "practice_name": bill.get("name", ""),
            "practice_code": inv.practice.practice_code if inv.practice else None,
            "practice_address": bill.get("address_lines", []),
            "invoices": [inv.invoice_number],
            "credit_notes": [c.number for c in credits],
            "session_dates": sorted({ln.service_date.isoformat() for ln in inv.lines
                                     if ln.pensionable and ln.id not in credited_lines}),
            "fees": str(net["fees"]),
            "pensionable_pay": str(net["pay"]),
            "employer": str(net["employer"]),
            "received_pay": str(round_money(received)),
            "deadline": (last_session(inv) + timedelta(days=TEN_WEEKS)).isoformat(),
            "form_a": {
                "status": rec.status if rec else "to_send",
                "sent_on": rec.sent_on.isoformat() if rec and rec.sent_on else None,
                "signed_on": rec.signed_on.isoformat() if rec and rec.signed_on else None,
                "document_id": rec.document_id if rec else None,
            },
        })  # fmt: skip
    return rows


def _form_b(s: Session, month: str, invoices: list[Invoice]) -> dict[str, Any]:
    """Form B: pensionable income *received* in ``month`` (from payments), any work month."""
    items = [r for inv in invoices for r in receipts(inv) if r["received_month"] == month]
    items.sort(key=lambda r: (r["paid_on"], r["invoice_number"] or ""))
    pay = round_money(sum((Decimal(r["pensionable_pay"]) for r in items), ZERO))
    employer = round_money(sum((Decimal(r["employer"]) for r in items), ZERO))
    rate = core.get_profile(s).employee_rate
    employee = round_money(pay * rate) if rate is not None else None
    return {
        "items": items,
        "pensionable_pay": str(pay),
        "employer": str(employer),
        "employee_rate": str(rate) if rate is not None else None,
        "employee": str(employee) if employee is not None else None,
        "total_payable": str(round_money(employer + employee)) if employee is not None else None,
        "due_by": form_b_due(month).isoformat(),
    }


def month_figures(s: Session, month: str, invoices: list[Invoice] | None = None) -> dict[str, Any]:
    """Form A rows for work done in ``month`` and the Form B for income received in it."""
    if invoices is None:
        invoices = _pension_invoices(s)
    profile = core.get_profile(s)
    forms_a = _forms_a(s, month, invoices)
    form_b = _form_b(s, month, invoices)
    pay, employer = Decimal(form_b["pensionable_pay"]), Decimal(form_b["employer"])
    employee = Decimal(form_b["employee"]) if form_b["employee"] is not None else None
    return {
        "month": month,
        "forms_a": forms_a,
        "form_b": form_b,
        "pcse": pcse_compare(s, month, pay, employer, employee),
        "locum": {
            "name": profile.legal_name,
            "professional_number": profile.professional_number,
            "pension_ref": profile.pension_ref,
        },
    }


def overview(s: Session) -> list[dict[str, Any]]:
    """One row per month with pensionable work or pensionable income, newest first."""
    invoices = _pension_invoices(s)
    subs = {p.month: p for p in s.scalars(select(PensionSubmission))}
    months = {work_month(i) for i in invoices}
    months |= {r["received_month"] for i in invoices for r in receipts(i)}
    out = []
    for m in sorted(months | set(subs), reverse=True):
        fig = month_figures(s, m, invoices)
        sub = subs.get(m)
        b = fig["form_b"]
        out.append({
            "month": m,
            "practices": len(fig["forms_a"]),
            "forms_a_signed": [a["form_a"]["status"] for a in fig["forms_a"]].count("signed"),
            "work_pay": str(round_money(sum((Decimal(a["pensionable_pay"])
                                             for a in fig["forms_a"]), ZERO))),
            "received_items": len(b["items"]),
            "pcse": fig["pcse"]["status"],
            "pensionable_pay": b["pensionable_pay"],
            "employer": b["employer"],
            "employee": b["employee"],
            "due_by": b["due_by"],
            "submitted_on": sub.submitted_on.isoformat() if sub else None,
            "changed_since_submitted": sub is not None and _key(sub.figures_json) != _key(fig),
            "ready": _month_ended(m) and bool(b["items"]),
        })  # fmt: skip
    return out


def _key(fig: dict[str, Any]) -> tuple[Any, ...]:
    """What a Form B submission contains: the received figures (not Form A progress)."""
    b = fig.get("form_b") or {}
    return (b.get("pensionable_pay"), b.get("employer"))


def _month_ended(month: str) -> bool:
    y, m = (int(x) for x in month.split("-"))
    today = core.today_london()
    return (today.year, today.month) > (y, m)


def mark_submitted(s: Session, month: str, submitted_on: date | None = None) -> PensionSubmission:
    fig = month_figures(s, month)
    if not fig["form_b"]["items"]:
        raise DomainError("pension.no_income", "No pensionable fees were received that month.")
    existing = s.scalars(select(PensionSubmission).where(PensionSubmission.month == month)).first()
    if existing is not None:
        raise Conflict("pension.already_submitted", "That month is already marked as submitted.")
    sub = PensionSubmission(
        month=month, submitted_on=submitted_on or core.today_london(), figures_json=fig
    )
    s.add(sub)
    core.audit(s, "pension.marked_submitted", month=month)
    s.commit()
    return sub


def unmark_submitted(s: Session, month: str) -> str | None:
    sub = s.scalars(select(PensionSubmission).where(PensionSubmission.month == month)).first()
    if sub is not None:
        from locuvi.services import trash

        item = trash.bin_submission(s, sub)
        s.delete(sub)
        core.audit(s, "pension.unmarked_submitted", month=month)
        s.commit()
        return item.id
    return None


# ------------------------------------------------------------------ Form A tracking

FORM_A_STATES = ("to_send", "sent", "signed")


def set_form_a(
    s: Session,
    month: str,
    practice_key: str,
    status: str,
    on: date | None = None,
    document_id: str | None = None,
) -> None:
    """Record Form A progress for one engagement (invoice): to_send → sent → signed."""
    if status not in FORM_A_STATES:
        raise DomainError("pension.bad_form_a_status", "Unknown Form A status.")
    fig = month_figures(s, month)
    if practice_key not in {a["key"] for a in fig["forms_a"]}:
        raise DomainError("pension.no_work", "No pensionable invoice for that Form A.")
    rec = s.scalars(
        select(FormARecord).where(
            FormARecord.month == month, FormARecord.practice_key == practice_key
        )
    ).first()
    on = on or core.today_london()
    if status == "to_send":
        if rec is not None:
            s.delete(rec)
    else:
        if rec is None:
            rec = FormARecord(month=month, practice_key=practice_key)
            s.add(rec)
        rec.status = status
        if status == "sent":
            rec.sent_on, rec.signed_on = on, None
        else:
            rec.sent_on = rec.sent_on or on
            rec.signed_on = on
        if document_id is not None:
            rec.document_id = document_id or None
    core.audit(s, "pension.form_a", month=month, status=status)
    s.commit()


# ------------------------------------------------------------------ PCSE comparison


def pcse_compare(
    s: Session, month: str, pay: Decimal, employer: Decimal, employee: Decimal | None
) -> dict[str, Any]:
    """Expected (from issued invoices) vs what PCSE shows. status: none | match | mismatch."""
    rec = s.get(PcseRecord, month)
    expected_total = round_money(employer + employee) if employee is not None else None
    out: dict[str, Any] = {
        "status": "none",
        "expected_pay": str(pay),
        "expected_contributions": str(expected_total) if expected_total is not None else None,
        "recorded_pay": None,
        "recorded_contributions": None,
        "difference": None,
    }
    if rec is None:
        return out
    out["recorded_pay"] = str(rec.pensionable_pay) if rec.pensionable_pay is not None else None
    out["recorded_contributions"] = (
        str(rec.contributions) if rec.contributions is not None else None
    )
    diffs = []
    if rec.pensionable_pay is not None:
        diffs.append(round_money(rec.pensionable_pay - pay))
    if rec.contributions is not None and expected_total is not None:
        diffs.append(round_money(rec.contributions - expected_total))
    if not diffs:
        return out
    worst = max(diffs, key=abs)
    out["difference"] = str(worst)
    out["status"] = "match" if all(d == 0 for d in diffs) else "mismatch"
    return out


def set_pcse(
    s: Session,
    month: str,
    pensionable_pay: Decimal | None,
    contributions: Decimal | None,
    source: str = "manual",
) -> None:
    for v in (pensionable_pay, contributions):
        if v is not None and (v < 0 or v.as_tuple().exponent < -2):  # type: ignore[operator]
            raise DomainError("pension.bad_amount", "Enter an amount in pounds and pence.")
    rec = s.get(PcseRecord, month)
    if pensionable_pay is None and contributions is None:
        if rec is not None:
            s.delete(rec)
        s.commit()
        return
    if rec is None:
        rec = PcseRecord(month=month)
        s.add(rec)
    rec.pensionable_pay, rec.contributions, rec.source = pensionable_pay, contributions, source
    core.audit(s, "pension.pcse_recorded", month=month, source=source)
    s.commit()


def import_pcse(s: Session, data: bytes) -> dict[str, int]:
    """CSV with a month/date column and pensionable pay and/or contributions columns.

    Several rows for one month are added together (e.g. one row per practice).
    """
    import csv
    import io

    from locuvi.services.bank import parse_amount, parse_date

    if len(data) > 2 * 1024 * 1024:
        raise DomainError("pension.pcse_too_large", "That file is too large.")
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise DomainError("pension.pcse_unreadable", "Couldn't read this file.")
    head = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> int | None:
        for i, h in enumerate(head):
            if any(n in h for n in names):
                return i
        return None

    mi = col("month", "period", "date")
    pi = col("pensionable pay", "pensionable earnings", "pay", "earnings")
    ci = col("contribution", "total paid", "amount paid")
    if mi is None or (pi is None and ci is None):
        raise DomainError("pension.pcse_unreadable", "Couldn't find month and amount columns.")
    sums: dict[str, list[Decimal | None]] = {}
    for r in rows[1:]:
        raw = r[mi].strip() if mi < len(r) else ""
        month = None
        if re.fullmatch(r"\d{4}-\d{2}", raw):
            month = raw
        else:
            d = parse_date(raw) or parse_date(f"01 {raw}") or parse_date(f"01/{raw}")
            month = f"{d.year:04d}-{d.month:02d}" if d else None
        if not month:
            continue
        acc = sums.setdefault(month, [None, None])
        for slot, idx in ((0, pi), (1, ci)):
            if idx is not None and idx < len(r):
                v = parse_amount(r[idx])
                if v is not None:
                    acc[slot] = round_money((acc[slot] or ZERO) + v)
    for month, (pay, contrib) in sums.items():
        set_pcse(s, month, pay, contrib, source="csv")
    return {"months": len(sums)}
