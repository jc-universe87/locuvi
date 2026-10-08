"""Monthly NHS pension figures for GP Locum Forms A and B, built from issued invoices.

Locuvi prepares the figures to copy onto the official forms; it does not submit anything.
Invoices are already one practice and one calendar month for pensionable work, so the
frozen invoice figures (basic fee, pensionable pay, employer contribution) are summed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError
from locuvi.models import Invoice, InvoiceStatus, PensionSubmission
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
        a["invoices"].append(inv.invoice_number)
        a["session_dates"].update(ln.service_date for ln in inv.lines if ln.pensionable)
        a["fees"] += inv.pensionable_basic_total or ZERO
        a["pensionable_pay"] += inv.pensionable_pay or ZERO
        a["employer"] += inv.employer_contribution or ZERO
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
        out.append(
            {
                "month": m,
                "practices": len(fig["forms_a"]),
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
