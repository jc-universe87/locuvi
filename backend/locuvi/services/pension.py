"""Monthly NHS pension figures for GP Locum Forms A and B, built from issued invoices.

Locuvi prepares the figures to copy onto the official forms; it does not submit anything.
Invoices are already one practice and one calendar month for pensionable work, so the
frozen invoice figures (basic fee, pensionable pay, employer contribution) are summed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError
from locuvi.models import FormARecord, Invoice, InvoiceStatus, PcseRecord, PensionSubmission
from locuvi.money import ZERO, round_money
from locuvi.services import core


def _month_of(inv: Invoice) -> str | None:
    dates = [ln.service_date for ln in inv.lines if ln.pensionable]
    if not dates or not inv.pension_enabled or not inv.pensionable_pay:
        return None
    d = min(dates)
    return f"{d.year:04d}-{d.month:02d}"


def _invoices_by_month(s: Session) -> dict[str, list[Invoice]]:
    out: dict[str, list[Invoice]] = defaultdict(list)
    for inv in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued)):
        m = _month_of(inv)
        if m:
            out[m].append(inv)
    return out


def month_figures(s: Session, month: str, invoices: list[Invoice] | None = None) -> dict[str, Any]:
    if invoices is None:
        invoices = _invoices_by_month(s).get(month, [])
    profile = core.get_profile(s)
    forms_a: dict[str, dict[str, Any]] = {}
    for inv in sorted(invoices, key=lambda i: i.invoice_number or ""):
        snap = inv.immutable_snapshot_json or {}
        bill = snap.get("bill_to", {})
        key = inv.practice_id or bill.get("name", "")
        a = forms_a.setdefault(
            key,
            {
                "key": key,
                "practice_name": bill.get("name", ""),
                "practice_code": inv.practice.practice_code if inv.practice else None,
                "practice_address": bill.get("address_lines", []),
                "invoices": [],
                "session_dates": set(),
                "fees": ZERO,
                "pensionable_pay": ZERO,
                "employer": ZERO,
            },
        )
        credits = list(inv.credit_notes)
        credited_lines = {i for c in credits for i in c.line_ids}
        a["invoices"].append(inv.invoice_number)
        a.setdefault("credit_notes", []).extend(c.number for c in credits)
        a["session_dates"].update(
            ln.service_date for ln in inv.lines if ln.pensionable and ln.id not in credited_lines
        )
        a["fees"] += (inv.pensionable_basic_total or ZERO) - sum(
            (c.pensionable_basic_total for c in credits), ZERO
        )
        a["pensionable_pay"] += (inv.pensionable_pay or ZERO) - sum(
            (c.pensionable_pay for c in credits), ZERO
        )
        a["employer"] += (inv.employer_contribution or ZERO) - sum(
            (c.employer_contribution for c in credits), ZERO
        )
    rows = []
    for a in forms_a.values():
        rows.append(
            {
                **a,
                "session_dates": [d.isoformat() for d in sorted(a["session_dates"])],
                "fees": str(round_money(a["fees"])),
                "pensionable_pay": str(round_money(a["pensionable_pay"])),
                "employer": str(round_money(a["employer"])),
            }
        )
    records = {
        r.practice_key: r for r in s.scalars(select(FormARecord).where(FormARecord.month == month))
    }
    for r in rows:
        rec = records.get(r["key"])
        r["form_a"] = {
            "status": rec.status if rec else "to_send",
            "sent_on": rec.sent_on.isoformat() if rec and rec.sent_on else None,
            "signed_on": rec.signed_on.isoformat() if rec and rec.signed_on else None,
            "document_id": rec.document_id if rec else None,
        }
    total_pay = round_money(sum((Decimal(r["pensionable_pay"]) for r in rows), ZERO))
    employer = round_money(sum((Decimal(r["employer"]) for r in rows), ZERO))
    rate = profile.employee_rate
    employee = round_money(total_pay * rate) if rate is not None else None
    return {
        "month": month,
        "forms_a": rows,
        "form_b": {
            "pensionable_pay": str(total_pay),
            "employer": str(employer),
            "employee_rate": str(rate) if rate is not None else None,
            "employee": str(employee) if employee is not None else None,
            "total_payable": str(round_money(employer + employee))
            if employee is not None
            else None,
        },
        "pcse": pcse_compare(s, month, total_pay, employer, employee),
        "locum": {
            "name": profile.legal_name,
            "professional_number": profile.professional_number,
            "pension_ref": profile.pension_ref,
        },
    }


def overview(s: Session) -> list[dict[str, Any]]:
    """One row per month with pensionable work, newest first, with submission state."""
    by_month = _invoices_by_month(s)
    subs = {p.month: p for p in s.scalars(select(PensionSubmission))}
    months = sorted(set(by_month) | set(subs), reverse=True)
    out = []
    for m in months:
        fig = month_figures(s, m, by_month.get(m, []))
        sub = subs.get(m)
        changed = sub is not None and _key(sub.figures_json) != _key(fig)
        fa = [a["form_a"]["status"] for a in fig["forms_a"]]
        out.append(
            {
                "month": m,
                "practices": len(fig["forms_a"]),
                "forms_a_signed": fa.count("signed"),
                "pcse": fig["pcse"]["status"],
                "pensionable_pay": fig["form_b"]["pensionable_pay"],
                "employer": fig["form_b"]["employer"],
                "employee": fig["form_b"]["employee"],
                "submitted_on": sub.submitted_on.isoformat() if sub else None,
                "changed_since_submitted": changed,
                "ready": _month_ended(m),
            }
        )
    return out


def _key(fig: dict[str, Any]) -> tuple[Any, ...]:
    # what was submitted: figures only (Form A progress and PCSE status are not figures)
    return (
        fig["form_b"]["pensionable_pay"],
        fig["form_b"]["employer"],
        tuple(sorted(a["invoices"] for a in fig["forms_a"])) if fig.get("forms_a") else (),
    )


def _month_ended(month: str) -> bool:
    y, m = (int(x) for x in month.split("-"))
    today = core.today_london()
    return (today.year, today.month) > (y, m)


def mark_submitted(s: Session, month: str, submitted_on: date | None = None) -> PensionSubmission:
    fig = month_figures(s, month)
    if not fig["forms_a"]:
        raise DomainError("pension.no_work", "No pensionable invoices for that month.")
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


def unmark_submitted(s: Session, month: str) -> None:
    sub = s.scalars(select(PensionSubmission).where(PensionSubmission.month == month)).first()
    if sub is not None:
        s.delete(sub)
        core.audit(s, "pension.unmarked_submitted", month=month)
        s.commit()


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
    """Record Form A progress for one practice-month: to_send → sent → signed."""
    if status not in FORM_A_STATES:
        raise DomainError("pension.bad_form_a_status", "Unknown Form A status.")
    fig = month_figures(s, month)
    if practice_key not in {a["key"] for a in fig["forms_a"]}:
        raise DomainError("pension.no_work", "No pensionable invoices for that practice and month.")
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
