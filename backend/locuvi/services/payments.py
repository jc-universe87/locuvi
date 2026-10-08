"""Payments received against issued invoices, and derived payment state."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import Invoice, InvoiceEvent, InvoiceStatus, Payment
from locuvi.money import ZERO, round_money
from locuvi.services import core


def paid_total(inv: Invoice) -> Decimal:
    return round_money(sum((p.amount for p in inv.payments), ZERO))


def payment_state(inv: Invoice, today: date | None = None) -> dict[str, Any]:
    """unpaid | part_paid | paid | overdue (unpaid/part after due date) | n/a for drafts/voids."""
    if inv.status != InvoiceStatus.issued or inv.grand_total is None:
        return {"state": "n/a", "paid": None, "outstanding": None, "days_overdue": 0}
    today = today or core.today_london()
    paid = paid_total(inv)
    outstanding = round_money(inv.grand_total - paid)
    if outstanding <= 0:
        state = "paid"
    elif inv.due_date and today > inv.due_date:
        state = "overdue"
    elif paid > 0:
        state = "part_paid"
    else:
        state = "unpaid"
    days = (today - inv.due_date).days if state == "overdue" and inv.due_date else 0
    last = max((p.paid_on for p in inv.payments), default=None)
    return {
        "state": state,
        "paid": str(paid),
        "outstanding": str(max(outstanding, ZERO)),
        "days_overdue": days,
        "paid_on": last.isoformat() if state == "paid" and last else None,
    }


def record_payment(
    s: Session,
    inv: Invoice,
    *,
    amount: Decimal | None = None,
    paid_on: date | None = None,
    method: str = "bank_transfer",
    reference: str | None = None,
) -> Payment:
    if inv.status != InvoiceStatus.issued:
        raise Conflict("payment.not_issued", "Only issued invoices can be paid.")
    outstanding = round_money((inv.grand_total or ZERO) - paid_total(inv))
    if outstanding <= 0:
        raise Conflict("payment.already_paid", "This invoice is already paid.")
    amount = outstanding if amount is None else amount
    if amount <= 0 or amount.as_tuple().exponent < -2:  # type: ignore[operator]
        raise DomainError("payment.amount_invalid", "Enter an amount above £0.00.")
    if amount > outstanding:
        raise DomainError(
            "payment.amount_too_high", "That is more than is owed.", outstanding=str(outstanding)
        )
    paid_on = paid_on or core.today_london()
    p = Payment(
        invoice_id=inv.id,
        paid_on=paid_on,
        amount=amount,
        method=method,
        reference=(reference or "").strip() or None,
    )
    s.add(p)
    inv.payments.append(p)
    s.add(
        InvoiceEvent(
            invoice_id=inv.id,
            event_type="payment_recorded",
            metadata_json={"amount": str(amount), "paid_on": paid_on.isoformat()},
        )
    )
    s.commit()
    return p


def delete_payment(s: Session, payment_id: str) -> Invoice:
    p = s.get(Payment, payment_id)
    if p is None:
        raise NotFound("payment.not_found", "Payment not found.")
    inv = p.invoice
    s.add(
        InvoiceEvent(
            invoice_id=inv.id, event_type="payment_removed", metadata_json={"amount": str(p.amount)}
        )
    )
    inv.payments.remove(p)
    s.delete(p)
    s.commit()
    return inv
