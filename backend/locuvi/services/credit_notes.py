"""Credit notes: correct an issued invoice after the practice has booked it.

An issued invoice never changes. A credit note is a separate, immutable document with its own
number series (default ``CN-0001``), frozen snapshot and PDF. It credits whole lines of one
invoice, priced with that invoice's frozen pension rates via the same Decimal rules, so the
pensionable pay and employer contribution come down by exactly the right amount. When the last
lines are credited, the totals are the invoice's remaining totals, so a fully credited invoice
nets to exactly £0.00 whatever the rounding of earlier partial credits.

Issue mirrors invoice issue: one BEGIN IMMEDIATE transaction, idempotency key, and a PDF failure
never consumes a number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import CreditNote, Invoice, InvoiceEvent, InvoiceStatus, utcnow
from locuvi.money import ZERO, LineInput, PensionPolicyValues, calculate_totals, round_money
from locuvi.pdf.render import render_invoice_pdf
from locuvi.services import core
from locuvi.storage.local import write_issued_pdf

log = logging.getLogger(__name__)

FIELDS = ("fee_subtotal", "pensionable_basic_total", "pensionable_pay", "employer_contribution",
          "grand_total")  # fmt: skip


@dataclass
class CreditTotals:
    fee_subtotal: Decimal
    pensionable_basic_total: Decimal
    pensionable_pay: Decimal
    employer_contribution: Decimal
    grand_total: Decimal

    def as_strings(self) -> dict[str, str]:
        return {f: str(getattr(self, f)) for f in FIELDS}


def for_invoice(s: Session, invoice_id: str) -> list[CreditNote]:
    return list(
        s.scalars(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice_id)
            .order_by(CreditNote.created_at)
        )
    )


def credited_total(s: Session, inv: Invoice) -> Decimal:
    return round_money(sum((c.grand_total for c in for_invoice(s, inv.id)), ZERO))


def _policy(inv: Invoice) -> PensionPolicyValues | None:
    snap = inv.immutable_snapshot_json or {}
    frac = (snap.get("totals") or {}).get("pensionable_fraction")
    if not inv.pension_enabled or inv.employer_rate is None or frac is None:
        return None
    return PensionPolicyValues(date(2000, 1, 1), Decimal(frac), inv.employer_rate)


def compute(s: Session, inv: Invoice, line_ids: list[str]) -> CreditTotals:
    if inv.status != InvoiceStatus.issued:
        raise Conflict("credit.not_issued", "Only issued invoices can be credited.")
    ids = list(dict.fromkeys(line_ids))
    if not ids:
        raise DomainError("credit.no_lines", "Choose at least one line to credit.")
    by_id = {ln.id: ln for ln in inv.lines}
    if any(i not in by_id for i in ids):
        raise DomainError("credit.bad_line", "That line is not on this invoice.")
    previous = for_invoice(s, inv.id)
    already = {i for c in previous for i in c.line_ids}
    if already & set(ids):
        raise Conflict("credit.already_credited", "Some of these lines are already credited.")
    if already | set(ids) == set(by_id):
        # Last credit: exactly what remains, so the invoice nets to zero.
        inv_totals = {f: getattr(inv, f) or ZERO for f in FIELDS}
        return CreditTotals(**{
            f: round_money(inv_totals[f] - sum((getattr(c, f) for c in previous), ZERO))
            for f in FIELDS
        })  # fmt: skip
    lines = [by_id[i] for i in ids]
    t = calculate_totals(
        [LineInput(ln.service_date, ln.quantity, ln.unit_price, ln.pensionable) for ln in lines],
        pension_enabled=inv.pension_enabled,
        policy=_policy(inv),
    )
    return CreditTotals(t.fee_subtotal, t.pensionable_basic_total, t.pensionable_pay,
                        t.employer_contribution, t.grand_total)  # fmt: skip


def _snapshot(inv: Invoice, number: str, credit_date: date, reason: str, lines: list[Any],
              totals: CreditTotals) -> dict[str, Any]:  # fmt: skip
    snap = inv.immutable_snapshot_json or {}
    inv_totals = snap.get("totals") or {}
    return {
        "kind": "credit_note",
        "invoice": {
            "number": number,
            "invoice_date": credit_date.isoformat(),
            "due_date": None,
            "reference": inv.invoice_number,
            "notes": None,
        },  # fmt: skip
        "credit": {
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "reason": reason,
        },
        "seller": snap.get("seller", {}),
        "bill_to": snap.get("bill_to", {}),
        "bank": {},
        "pension": snap.get("pension", {}),
        "lines": [
            {
                "service_date": ln.service_date.isoformat(),
                "description": ln.description,
                "unit": ln.unit,
                "quantity": str(ln.quantity),
                "unit_price": str(ln.unit_price),
                "amount": str(ln.amount),
                "pensionable": ln.pensionable,
            }
            for ln in lines
        ],  # fmt: skip
        "totals": {
            **totals.as_strings(),
            "non_pensionable_total": str(
                round_money(totals.fee_subtotal - totals.pensionable_basic_total)
            ),
            "pensionable_fraction": inv_totals.get("pensionable_fraction"),
            "employer_rate": inv_totals.get("employer_rate"),
            "vat_amount": None,
        },
    }


def issue(
    settings: Settings,
    invoice_id: str,
    line_ids: list[str],
    reason: str,
    idempotency_key: str,
    *,
    render: Any = render_invoice_pdf,
    after_issue: Any = None,
) -> CreditNote:
    reason = (reason or "").strip()[:1000]
    if not reason:
        raise DomainError("credit.reason_required", "Say why you are crediting this invoice.")
    key = (idempotency_key or "").strip()
    if not (8 <= len(key) <= 100):
        raise DomainError("invoice.idempotency_key_required", "An idempotency key is required.")
    with db.immediate_session() as s:
        done = s.scalars(select(CreditNote).where(CreditNote.idempotency_key == key)).first()
        if done is not None:
            if done.invoice_id != invoice_id:
                raise Conflict("invoice.idempotency_key_reused", "Idempotency key already used.")
            return done
        inv = s.get(Invoice, invoice_id)
        if inv is None:
            raise NotFound("invoice.not_found", "Invoice not found.")
        totals = compute(s, inv, line_ids)
        seq = core.get_sequence(s)
        number = core.format_number(seq.credit_prefix, seq.credit_next_number, seq.padding)
        if s.scalars(select(CreditNote.id).where(CreditNote.number == number)).first():
            raise Conflict("sequence.number_taken", f"Credit note number {number} is already used.",
                           number=number)  # fmt: skip
        credit_date = core.today_london()
        lines = [ln for ln in inv.lines if ln.id in set(line_ids)]
        snapshot = _snapshot(inv, number, credit_date, reason, lines, totals)
        cn = CreditNote(
            number=number, invoice_id=inv.id, credit_date=credit_date, reason=reason,
            line_ids=[ln.id for ln in lines], snapshot_json=snapshot, idempotency_key=key,
            local_pdf_path="", local_pdf_sha256="",
            **{f: getattr(totals, f) for f in FIELDS},
        )  # fmt: skip
        s.add(cn)
        s.flush()
        stored = write_issued_pdf(settings.data_dir, cn.id, render(snapshot), folder="credit")
        cn.local_pdf_path, cn.local_pdf_sha256 = stored.relative_path, stored.sha256
        seq.credit_next_number += 1
        s.add(InvoiceEvent(invoice_id=inv.id, event_type="credited",
                           metadata_json={"number": number, "amount": str(totals.grand_total),
                                          "at": utcnow().isoformat()}))  # fmt: skip
        if after_issue is not None:
            after_issue(s, cn)  # queues the Nextcloud copy in the same transaction
        s.commit()
        log.info("credit note issued number=%s invoice=%s", number, inv.invoice_number)
        return cn


def as_dict(cn: CreditNote) -> dict[str, Any]:
    return {
        "id": cn.id,
        "number": cn.number,
        "invoice_id": cn.invoice_id,
        "credit_date": cn.credit_date,
        "reason": cn.reason,
        "line_ids": cn.line_ids,
        **{f: str(getattr(cn, f)) for f in FIELDS},
    }
