"""Income reports by UK tax year, CSV export, year-end pack, and the Today overview."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.config import Settings
from locuvi.models import Invoice, InvoiceStatus, Practice, WorkSession
from locuvi.money import ZERO, round_money
from locuvi.services import core, diary, payments, pension
from locuvi.storage.local import resolve


def tax_year_of(d: date) -> int:
    """UK tax year label by its starting year: 6 Apr 2026 – 5 Apr 2027 → 2026."""
    return d.year if (d.month, d.day) >= (4, 6) else d.year - 1


def tax_year_bounds(year: int) -> tuple[date, date]:
    return date(year, 4, 6), date(year + 1, 4, 5)


def _issued_in(s: Session, start: date, end: date) -> list[Invoice]:
    return list(
        s.scalars(
            select(Invoice)
            .where(
                Invoice.status == InvoiceStatus.issued,
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            .order_by(Invoice.invoice_date, Invoice.invoice_number)
        )
    )


def summary(s: Session, year: int) -> dict[str, Any]:
    start, end = tax_year_bounds(year)
    invs = _issued_in(s, start, end)
    by_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_practice: dict[str, dict[str, Any]] = {}
    totals = {"invoiced": ZERO, "fees": ZERO, "employer": ZERO, "paid": ZERO, "outstanding": ZERO}
    for inv in invs:
        gt = inv.grand_total or ZERO
        assert inv.invoice_date is not None
        by_month[f"{inv.invoice_date.year:04d}-{inv.invoice_date.month:02d}"] += gt
        name = (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", "")
        p = by_practice.setdefault(name, {"practice": name, "invoices": 0, "total": ZERO})
        p["invoices"] += 1
        p["total"] += gt
        paid = payments.paid_total(inv)
        totals["invoiced"] += gt
        totals["fees"] += inv.fee_subtotal or ZERO
        totals["employer"] += inv.employer_contribution or ZERO
        totals["paid"] += paid
        totals["outstanding"] += max(gt - paid, ZERO)
    months = []
    d = start.replace(day=1)
    while d <= end:
        key = f"{d.year:04d}-{d.month:02d}"
        months.append({"month": key, "total": str(round_money(by_month.get(key, ZERO)))})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    current = tax_year_of(core.today_london())
    first = min(
        (
            tax_year_of(i.invoice_date)
            for i in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued))
            if i.invoice_date
        ),
        default=current,
    )
    return {
        "tax_year": year,
        "label": f"{year}/{str(year + 1)[-2:]}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "available_years": list(range(current, first - 1, -1)),
        "invoice_count": len(invs),
        "totals": {k: str(round_money(v)) for k, v in totals.items()},
        "months": months,
        "practices": sorted(
            ({**p, "total": str(round_money(p["total"]))} for p in by_practice.values()),
            key=lambda p: Decimal(p["total"]),
            reverse=True,
        ),
    }


CSV_FIELDS = [
    "invoice_number",
    "status",
    "invoice_date",
    "due_date",
    "practice",
    "work_start",
    "work_end",
    "fee_subtotal",
    "pensionable_basic",
    "pensionable_pay",
    "employer_rate",
    "employer_contribution",
    "grand_total",
    "paid",
    "outstanding",
    "paid_on",
    "void_reason",
]


def invoices_csv(s: Session, start: date, end: date) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    rows = s.scalars(
        select(Invoice)
        .where(
            Invoice.status != InvoiceStatus.draft,
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
        )
        .order_by(Invoice.invoice_date, Invoice.invoice_number)
    )
    for inv in rows:
        st = payments.payment_state(inv)
        w.writerow(
            {
                "invoice_number": inv.invoice_number,
                "status": inv.status,
                "invoice_date": inv.invoice_date,
                "due_date": inv.due_date,
                "practice": (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", ""),
                "work_start": inv.work_start_date,
                "work_end": inv.work_end_date,
                "fee_subtotal": inv.fee_subtotal,
                "pensionable_basic": inv.pensionable_basic_total,
                "pensionable_pay": inv.pensionable_pay,
                "employer_rate": inv.employer_rate or "",
                "employer_contribution": inv.employer_contribution,
                "grand_total": inv.grand_total,
                "paid": st["paid"] or "",
                "outstanding": st["outstanding"] or "",
                "paid_on": st.get("paid_on") or "",
                "void_reason": inv.void_reason or "",
            }
        )
    return buf.getvalue()


def year_pack(s: Session, settings: Settings, year: int) -> bytes:
    """ZIP with every issued/voided PDF of the tax year plus the CSV summary."""
    start, end = tax_year_bounds(year)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"locuvi-invoices-{year}-{year + 1}.csv", invoices_csv(s, start, end))
        for inv in s.scalars(
            select(Invoice).where(
                Invoice.status != InvoiceStatus.draft,
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
        ):
            path = resolve(settings.data_dir, inv.local_pdf_path or "")
            if path.is_file():
                suffix = "-VOID" if inv.status == InvoiceStatus.voided else ""
                z.write(path, f"invoices/{inv.invoice_number}{suffix}.pdf")
    return buf.getvalue()


def today_overview(s: Session) -> dict[str, Any]:
    """Everything that needs the owner's attention, in priority order."""
    today = core.today_london()
    profile = core.get_profile(s)
    has_practice = s.scalars(select(Practice.id).limit(1)).first() is not None
    issued = list(s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued)))
    unpaid = []
    for inv in issued:
        st = payments.payment_state(inv, today)
        if st["state"] in {"unpaid", "part_paid", "overdue"}:
            unpaid.append(
                {
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "practice_name": (inv.immutable_snapshot_json or {})
                    .get("bill_to", {})
                    .get("name"),
                    "due_date": inv.due_date,
                    "outstanding": st["outstanding"],
                    "state": st["state"],
                    "days_overdue": st["days_overdue"],
                }
            )
    unpaid.sort(key=lambda u: (u["state"] != "overdue", u["due_date"] or today))
    drafts = [
        {
            "id": d.id,
            "practice_name": d.practice.name if d.practice else None,
            "grand_total": str(d.grand_total) if d.grand_total is not None else None,
            "work_start_date": d.work_start_date,
            "work_end_date": d.work_end_date,
        }
        for d in s.scalars(
            select(Invoice)
            .where(Invoice.status == InvoiceStatus.draft)
            .order_by(Invoice.updated_at.desc())
        )
    ]
    upcoming = [
        {"id": w.id, "date": w.date, "unit": w.unit, "practice_name": w.practice.name}
        for w in s.scalars(
            select(WorkSession)
            .where(
                WorkSession.status == "active",
                WorkSession.date > today,
                WorkSession.date <= today + timedelta(days=14),
            )
            .order_by(WorkSession.date)
        )
    ]
    pension_due = [m for m in pension.overview(s) if m["ready"] and not m["submitted_on"]]
    month_start = today.replace(day=1)
    this_month = sum(
        (i.grand_total or ZERO for i in issued if i.invoice_date and i.invoice_date >= month_start),
        ZERO,
    )
    return {
        "today": today,
        "greeting_name": profile.legal_name,
        "setup": {
            "completed": profile.setup_completed,
            "profile": bool(profile.legal_name and profile.bank_account_number),
            "practice": has_practice,
        },
        "ready_to_invoice": diary.ready_to_invoice(s),
        "drafts": drafts,
        "unpaid": unpaid,
        "outstanding_total": str(
            round_money(sum((Decimal(u["outstanding"]) for u in unpaid), ZERO))
        ),
        "overdue_count": sum(1 for u in unpaid if u["state"] == "overdue"),
        "pension_due": pension_due,
        "upcoming": upcoming,
        "this_month_invoiced": str(round_money(this_month)),
        "tax_year": summary(s, tax_year_of(today))["totals"],
    }
