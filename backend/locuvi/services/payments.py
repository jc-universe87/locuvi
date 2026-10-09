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


def credited_total(inv: Invoice) -> Decimal:
    return round_money(sum((c.grand_total for c in inv.credit_notes), ZERO))


def outstanding(inv: Invoice) -> Decimal:
    """What is still owed: total − credit notes − payments (never below zero)."""
    if inv.grand_total is None:
        return ZERO
    return max(round_money(inv.grand_total - credited_total(inv) - paid_total(inv)), ZERO)


def payment_state(inv: Invoice, today: date | None = None) -> dict[str, Any]:
    """unpaid | part_paid | paid | overdue | credited (fully credited, nothing paid) |
    refund_due (more was paid than is owed after credit notes) | n/a."""
    if inv.status != InvoiceStatus.issued or inv.grand_total is None:
        return {"state": "n/a", "paid": None, "outstanding": None, "days_overdue": 0}
    today = today or core.today_london()
    paid = paid_total(inv)
    credited = credited_total(inv)
    outstanding = round_money(inv.grand_total - credited - paid)
    refund_due = max(round_money(-outstanding), ZERO)
    if refund_due > 0:
        state = "refund_due"
    elif credited > 0 and credited >= inv.grand_total and paid == 0:
        state = "credited"
    elif outstanding <= 0:
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
        "credited": str(credited),
        "paid": str(paid),
        "outstanding": str(max(outstanding, ZERO)),
        "refund_due": str(refund_due),
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
    commit: bool = True,
) -> Payment:
    """Record money received. ``commit=False`` lets a caller add several payments (and its own
    changes) and commit them as one transaction."""
    if inv.status != InvoiceStatus.issued:
        raise Conflict("payment.not_issued", "Only issued invoices can be paid.")
    outstanding = round_money((inv.grand_total or ZERO) - credited_total(inv) - paid_total(inv))
    if outstanding <= 0:
        raise Conflict("payment.already_paid", "Nothing is owed on this invoice.")
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
    if commit:
        s.commit()
    else:
        s.flush()
    return p


def delete_payment(s: Session, payment_id: str, *, commit: bool = True) -> Invoice:
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
    if commit:
        s.commit()
    else:
        s.flush()
    return inv


def record_refund(
    s: Session,
    inv: Invoice,
    *,
    amount: Decimal | None = None,
    paid_on: date | None = None,
    reference: str | None = None,
) -> Payment:
    """Money paid back to the practice (after a credit note on a paid invoice).

    Stored as a negative payment so every total (owed, Form B, cash basis) stays consistent.
    """
    st = payment_state(inv)
    due = Decimal(st.get("refund_due") or "0")
    if due <= 0:
        raise Conflict("refund.none_due", "No refund is owed on this invoice.")
    amount = due if amount is None else amount
    if amount <= 0 or amount.as_tuple().exponent < -2:  # type: ignore[operator]
        raise DomainError("payment.amount_invalid", "Enter an amount above £0.00.")
    if amount > due:
        raise DomainError("refund.too_high", "That is more than the refund owed.", due=str(due))
    paid_on = paid_on or core.today_london()
    p = Payment(
        invoice_id=inv.id,
        paid_on=paid_on,
        amount=-amount,
        method="refund",
        reference=(reference or "").strip() or None,
    )
    s.add(p)
    inv.payments.append(p)
    meta = {"amount": str(amount), "paid_on": paid_on.isoformat()}
    s.add(InvoiceEvent(invoice_id=inv.id, event_type="refund_recorded", metadata_json=meta))
    s.commit()
    return p
