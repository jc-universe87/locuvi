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
from locuvi.models import Invoice, InvoiceStatus, Payment, Practice, WorkSession
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


def tax_month(d: date) -> str:
    """Tax months run 6th → 5th; labelled by the calendar month they start in."""
    shifted = d - timedelta(days=5)
    return f"{shifted.year:04d}-{shifted.month:02d}"


def _tax_months(year: int) -> list[str]:
    return [f"{year + (m < 4):04d}-{m:02d}" for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)]


def receipts_in(s: Session, start: date, end: date) -> list[dict[str, Any]]:
    """Every payment (and refund) dated in the period, split into fee / employer / pensionable."""
    out = []
    invs = {p.invoice_id for p in s.scalars(
        select(Payment).where(Payment.paid_on >= start, Payment.paid_on <= end))}  # fmt: skip
    for inv_id in invs:
        inv = s.get(Invoice, inv_id)
        if inv is None:
            continue
        by_payment = {r["payment_id"]: r for r in pension.receipts(inv)}
        for p in inv.payments:
            if not (start <= p.paid_on <= end):
                continue
            r = by_payment.get(p.id, {})
            employer = Decimal(r.get("employer", "0"))
            out.append({
                "paid_on": p.paid_on, "invoice_number": inv.invoice_number,
                "practice": (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", ""),
                "amount": p.amount, "employer": employer, "fees": round_money(p.amount - employer),
                "pensionable_pay": Decimal(r.get("pensionable_pay", "0")),
                "method": p.method, "reference": p.reference or "",
            })  # fmt: skip
    return sorted(out, key=lambda r: (r["paid_on"], r["invoice_number"] or ""))


def summary(s: Session, year: int, basis: str | None = None) -> dict[str, Any]:
    """Tax-year report on the chosen basis.

    - ``cash`` (HMRC default for most sole traders): income when the money is received.
    - ``accruals`` (traditional): income when invoiced; credit notes when issued.
    Both views are always computed; ``basis`` picks which one is the headline.
    """
    from locuvi.models import CreditNote

    basis = basis or core.get_profile(s).accounting_basis or "cash"
    if basis not in {"cash", "accruals"}:
        basis = "cash"
    start, end = tax_year_bounds(year)
    invs = _issued_in(s, start, end)
    acc: dict[str, Decimal] = defaultdict(lambda: ZERO)
    acc_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    acc_practice: dict[str, dict[str, Any]] = {}
    outstanding = ZERO
    for inv in invs:
        gt = inv.grand_total or ZERO
        acc_month[tax_month(inv.invoice_date or start)] += gt
        name = (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", "")
        pr = acc_practice.setdefault(name, {"practice": name, "invoices": 0, "total": ZERO})
        pr["invoices"] += 1
        pr["total"] += gt
        acc["income"] += gt
        acc["fees"] += inv.fee_subtotal or ZERO
        acc["employer"] += inv.employer_contribution or ZERO
        acc["pensionable_pay"] += inv.pensionable_pay or ZERO
        outstanding += payments.outstanding(inv)
    credited = ZERO
    for cn in s.scalars(
        select(CreditNote).where(CreditNote.credit_date >= start, CreditNote.credit_date <= end)
    ):
        credited += cn.grand_total
        acc["income"] -= cn.grand_total
        acc["fees"] -= cn.fee_subtotal
        acc["employer"] -= cn.employer_contribution
        acc["pensionable_pay"] -= cn.pensionable_pay
        acc_month[tax_month(cn.credit_date)] -= cn.grand_total
        name = cn.snapshot_json.get("bill_to", {}).get("name", "")
        if name in acc_practice:
            acc_practice[name]["total"] -= cn.grand_total

    cash: dict[str, Decimal] = defaultdict(lambda: ZERO)
    cash_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    cash_practice: dict[str, dict[str, Any]] = {}
    received = receipts_in(s, start, end)
    for r in received:
        cash["income"] += r["amount"]
        cash["fees"] += r["fees"]
        cash["employer"] += r["employer"]
        cash["pensionable_pay"] += r["pensionable_pay"]
        cash_month[tax_month(r["paid_on"])] += r["amount"]
        pr = cash_practice.setdefault(r["practice"], {"practice": r["practice"], "invoices": 0,
                                                       "total": ZERO})  # fmt: skip
        pr["invoices"] += 1
        pr["total"] += r["amount"]

    head, by_month, by_practice = (
        (cash, cash_month, cash_practice) if basis == "cash" else (acc, acc_month, acc_practice)
    )
    totals = {
        "income": head["income"],
        "invoiced": acc["income"],
        "paid": cash["income"],  # money received in the tax year
        "outstanding": outstanding,
        "credited": credited,
        "fees": head["fees"],
        "employer": head["employer"],
        "pensionable_pay": head["pensionable_pay"],
    }
    current = tax_year_of(core.today_london())
    first = min(
        (
            tax_year_of(i.invoice_date)
            for i in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued))
            if i.invoice_date
        ),
        default=current,
    )
    rate = core.get_profile(s).employee_rate
    self_assessment = {
        # Figures for the owner's accountant — not tax advice.
        "basis": basis,
        "fees": str(round_money(head["fees"])),
        "employer_contributions": str(round_money(head["employer"])),
        "pensionable_pay": str(round_money(head["pensionable_pay"])),
        "employee_rate": str(rate) if rate is not None else None,
        "employee_contributions_estimate": (
            str(round_money(head["pensionable_pay"] * rate)) if rate is not None else None
        ),
    }
    return {
        "basis": basis,
        "self_assessment": self_assessment,
        "tax_year": year,
        "label": f"{year}/{str(year + 1)[-2:]}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "available_years": list(range(current, first - 1, -1)),
        "invoice_count": len(invs),
        "receipt_count": len(received),
        "totals": {k: str(round_money(v)) for k, v in totals.items()},
        "months": [
            {"month": m, "total": str(round_money(by_month.get(m, ZERO)))}
            for m in _tax_months(year)
        ],
        "practices": sorted(
            ({**p, "total": str(round_money(p["total"]))} for p in by_practice.values()),
            key=lambda p: Decimal(p["total"]),
            reverse=True,
        ),
    }


RECEIPT_FIELDS = ["paid_on", "invoice_number", "practice", "amount", "fees", "employer",
                  "pensionable_pay", "method", "reference"]  # fmt: skip


def receipts_csv(s: Session, start: date, end: date) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=RECEIPT_FIELDS)
    w.writeheader()
    for r in receipts_in(s, start, end):
        w.writerow({k: r[k] for k in RECEIPT_FIELDS})
    return buf.getvalue()


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
        z.writestr(f"locuvi-receipts-{year}-{year + 1}.csv", receipts_csv(s, start, end))
        from locuvi.models import CreditNote

        for cn in s.scalars(
            select(CreditNote).where(CreditNote.credit_date >= start, CreditNote.credit_date <= end)
        ):
            cpath = resolve(settings.data_dir, cn.local_pdf_path)
            if cpath.is_file():
                z.write(cpath, f"credit-notes/{cn.number}.pdf")
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
