"""Invoice drafting, analysis, immutable issue, void, duplicate and split."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import Conflict, DomainError, NotFound, ValidationFailed
from locuvi.models import (
    Invoice,
    InvoiceEvent,
    InvoiceLine,
    InvoiceStatus,
    LineUnit,
    PensionPolicy,
    Practice,
    VatStatus,
    utcnow,
)
from locuvi.money import (
    ROUNDING_DESCRIPTION,
    LineInput,
    Totals,
    basic_from_inclusive,
    calculate_totals,
    line_amount,
    pensionable_months,
)
from locuvi.pdf.render import render_invoice_pdf
from locuvi.services import branding, core
from locuvi.storage.local import write_issued_pdf

log = logging.getLogger("locuvi.invoices")

SNAPSHOT_SCHEMA_VERSION = 1
MAX_LINES = 200


@dataclass
class LineData:
    service_date: date
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    pensionable: bool
    agreed_rate: Decimal | None = None  # rate agreed including the employer contribution


@dataclass
class Issue:
    code: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "params": self.params}


@dataclass
class Analysis:
    totals: Totals
    policy: PensionPolicy | None
    blocking: list[Issue]
    warnings: list[Issue]
    work_start: date | None
    work_end: date | None
    months: list[tuple[int, int]]
    unit_prices: tuple[Decimal, ...] = ()  # effective prices (inclusive rates converted)


# --------------------------------------------------------------------------- lines


def validate_line(ln: LineData, index: int) -> None:
    if ln.unit not in LineUnit.__members__:
        raise DomainError("line.invalid_unit", f"Line {index + 1}: unknown unit", line=index)
    if ln.quantity <= 0:
        raise DomainError(
            "line.quantity_positive", f"Line {index + 1}: quantity must be positive", line=index
        )
    if ln.unit_price < 0:
        raise DomainError(
            "line.price_non_negative", f"Line {index + 1}: rate cannot be negative", line=index
        )
    if ln.quantity.as_tuple().exponent < -2 or ln.unit_price.as_tuple().exponent < -2:  # type: ignore[operator]
        raise DomainError(
            "line.too_many_decimals",
            f"Line {index + 1}: use at most 2 decimal places",
            line=index,
        )
    if ln.quantity > Decimal("10000") or ln.unit_price > Decimal("1000000"):
        raise DomainError("line.too_large", f"Line {index + 1}: value too large", line=index)
    a = ln.agreed_rate
    if a is not None and (a < 0 or a > Decimal("1000000") or a.as_tuple().exponent < -2):  # type: ignore[operator]
        raise DomainError(
            "line.bad_agreed_rate", f"Line {index + 1}: check the agreed rate", line=index
        )


def _line_inputs(
    lines: Sequence[LineData | InvoiceLine], prices: Sequence[Decimal] | None = None
) -> list[LineInput]:
    return [
        LineInput(
            service_date=ln.service_date,
            quantity=ln.quantity,
            unit_price=prices[i] if prices is not None else ln.unit_price,
            pensionable=ln.pensionable,
        )
        for i, ln in enumerate(lines)
    ]


def effective_prices(
    lines: Sequence[LineData | InvoiceLine], pension_enabled: bool, policy: PensionPolicy | None
) -> tuple[Decimal, ...]:
    """Unit prices to invoice: an inclusive agreed rate becomes the basic fee when pension
    applies to the line, and is charged as agreed when it does not."""
    values = core.policy_values(policy) if policy is not None else None
    out = []
    for ln in lines:
        agreed = getattr(ln, "agreed_rate", None)
        if agreed is None:
            out.append(ln.unit_price)
        elif pension_enabled and ln.pensionable and values is not None:
            out.append(basic_from_inclusive(agreed, values))
        else:
            out.append(agreed)
    return tuple(out)


# ------------------------------------------------------------------------ analysis


def analyse(
    s: Session,
    *,
    lines: Sequence[LineData | InvoiceLine],
    pension_enabled: bool,
    practice: Practice | None,
    for_issue: bool = False,
    reference: str | None = None,
) -> Analysis:
    blocking: list[Issue] = []
    warnings: list[Issue] = []
    raw = _line_inputs(lines)
    dates = sorted(ln.service_date for ln in raw)
    work_start = dates[0] if dates else None
    work_end = dates[-1] if dates else None

    months = pensionable_months(raw) if pension_enabled else []
    pension_dates = sorted(ln.service_date for ln in raw if ln.pensionable)
    policy = None
    if pension_enabled and pension_dates:
        policy = core.policy_for_date(s, pension_dates[0])
        if policy is None:
            blocking.append(
                Issue(
                    "invoice.no_pension_policy",
                    "No employer contribution rate is configured for these work dates.",
                    {"date": pension_dates[0].isoformat()},
                )
            )
        elif len(months) == 1:
            later = core.policy_for_date(s, pension_dates[-1])
            if later is not None and later.id != policy.id:
                blocking.append(
                    Issue(
                        "invoice.pension_policy_changes",
                        "The employer contribution rate changes within these work dates; "
                        "split the invoice at the change date.",
                        {"date": later.effective_from.isoformat()},
                    )
                )

    prices = effective_prices(lines, pension_enabled, policy)
    inputs = _line_inputs(lines, prices)
    totals = calculate_totals(
        inputs,
        pension_enabled=pension_enabled,
        policy=core.policy_values(policy) if policy else None,
    )
    agreed_lines = [ln for ln in lines if getattr(ln, "agreed_rate", None) is not None]
    if agreed_lines and totals.employer_contribution > 0:
        agreed_total = sum(
            (
                line_amount(ln.quantity, ln.agreed_rate)  # type: ignore[arg-type]
                if getattr(ln, "agreed_rate", None) is not None
                else line_amount(ln.quantity, p)
                for ln, p in zip(lines, prices, strict=True)
            ),
            Decimal("0"),
        )
        if agreed_total != totals.grand_total:
            warnings.append(
                Issue(
                    "invoice.inclusive_rounding",
                    "The agreed all-in rates add up to a slightly different total because "
                    "each fee is rounded to the penny.",
                    {"agreed": str(agreed_total), "total": str(totals.grand_total),
                     "difference": str(totals.grand_total - agreed_total)},
                )
            )  # fmt: skip

    if len(months) > 1:
        blocking.append(
            Issue(
                "invoice.pensionable_multi_month",
                "Pensionable sessions span more than one calendar month. "
                "Split the invoice by month before issuing.",
                {"months": [f"{y:04d}-{m:02d}" for y, m in months]},
            )
        )
    all_months = sorted({(d.year, d.month) for d in dates})
    if len(all_months) > 1 and len(months) <= 1:
        warnings.append(
            Issue(
                "invoice.lines_multi_month",
                "Work dates span more than one calendar month.",
                {"months": [f"{y:04d}-{m:02d}" for y, m in all_months]},
            )
        )
    if (
        practice is not None
        and practice.rate_includes_pension
        and totals.pensionable_basic_total > 0
        and any(ln.pensionable and getattr(ln, "agreed_rate", None) is None for ln in lines)
    ):
        warnings.append(
            Issue(
                "invoice.practice_rate_inclusive",
                "This practice's agreed rate is recorded as inclusive of the employer pension "
                "contribution. Check you are not adding it twice.",
            )
        )
    if practice is not None and practice.po_required and not reference:
        warnings.append(
            Issue(
                "invoice.po_required",
                "This practice needs a purchase order number on its invoices.",
                {"practice": practice.name},
            )
        )
    if practice is not None and practice.invoice_instructions:
        warnings.append(
            Issue(
                "invoice.practice_instructions",
                practice.invoice_instructions,
                {"text": practice.invoice_instructions},
            )
        )
    if pension_enabled and inputs and not any(ln.pensionable for ln in inputs):
        warnings.append(
            Issue(
                "invoice.no_pensionable_lines",
                "No line is marked pensionable, so no employer contribution is added.",
            )
        )

    if for_issue:
        blocking.extend(_issue_preflight(s, lines, practice, totals))
    return Analysis(totals, policy, blocking, warnings, work_start, work_end, months, tuple(prices))


def _issue_preflight(
    s: Session,
    lines: Sequence[LineData | InvoiceLine],
    practice: Practice | None,
    totals: Totals,
) -> list[Issue]:
    problems: list[Issue] = []
    profile = core.get_profile(s)
    missing = [
        f
        for f in ("legal_name", "address_lines", "bank_account_holder")
        if not (getattr(profile, f) or "").strip()
    ]
    if len(profile.bank_sort_code) != 6:
        missing.append("bank_sort_code")
    if len(profile.bank_account_number) != 8:
        missing.append("bank_account_number")
    if missing:
        problems.append(
            Issue(
                "profile.incomplete",
                "Complete your invoicing name, address and bank details in Settings.",
                {"fields": missing},
            )
        )
    if profile.vat_status != VatStatus.not_vat_registered:
        problems.append(
            Issue(
                "invoice.vat_unsupported",
                "VAT invoices are not supported in this version. Issuing is blocked rather "
                "than producing an incomplete VAT invoice.",
            )
        )
    if practice is None:
        problems.append(Issue("invoice.no_practice", "Choose a practice to bill."))
    elif not practice.billing_address.strip():
        problems.append(Issue("practice.no_address", "The practice needs a billing address."))
    if not lines:
        problems.append(Issue("invoice.no_lines", "Add at least one work line."))
    for i, ln in enumerate(lines):
        if not ln.description.strip():
            problems.append(
                Issue("line.no_description", f"Line {i + 1} needs a description.", {"line": i})
            )
    if lines and totals.grand_total <= 0:
        problems.append(Issue("invoice.zero_total", "The invoice total must be above £0.00."))
    return problems


# --------------------------------------------------------------------------- drafts


def get_invoice(s: Session, invoice_id: str) -> Invoice:
    inv = s.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("invoice.not_found", "Invoice not found.")
    return inv


def _require_draft(inv: Invoice) -> None:
    if inv.status != InvoiceStatus.draft:
        raise Conflict(
            "invoice.not_draft",
            "Issued invoices cannot be changed. Void it or duplicate it to a new draft.",
        )


def _set_lines(inv: Invoice, lines: Sequence[LineData]) -> None:
    if len(lines) > MAX_LINES:
        raise DomainError("invoice.too_many_lines", "Too many lines.", max=MAX_LINES)
    for i, ln in enumerate(lines):
        validate_line(ln, i)
    inv.lines.clear()
    for i, ln in enumerate(lines):
        inv.lines.append(
            InvoiceLine(
                service_date=ln.service_date,
                description=ln.description.strip(),
                unit=ln.unit,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=Decimal("0"),
                pensionable=ln.pensionable,
                agreed_rate=ln.agreed_rate,
                sort_order=i,
            )
        )


def _refresh_draft_cache(s: Session, inv: Invoice) -> Analysis:
    a = analyse(
        s,
        lines=inv.lines,
        pension_enabled=inv.pension_enabled,
        practice=inv.practice,
        reference=inv.reference,
    )
    for ln, price, amount in zip(inv.lines, a.unit_prices, a.totals.line_amounts, strict=True):
        ln.unit_price, ln.amount = price, amount
    inv.fee_subtotal = a.totals.fee_subtotal
    inv.pensionable_basic_total = a.totals.pensionable_basic_total
    inv.pensionable_pay = a.totals.pensionable_pay
    inv.employer_rate = a.totals.employer_rate
    inv.employer_contribution = a.totals.employer_contribution
    inv.vat_amount = None
    inv.grand_total = a.totals.grand_total
    inv.work_start_date = a.work_start
    inv.work_end_date = a.work_end
    inv.pension_policy_id = a.policy.id if a.policy else None
    return a


def _practice(s: Session, practice_id: str | None) -> Practice | None:
    if practice_id is None:
        return None
    p = s.get(Practice, practice_id)
    if p is None:
        raise NotFound("practice.not_found", "Practice not found.")
    return p


_UNSET: Any = object()


def save_draft(
    s: Session,
    inv: Invoice | None,
    *,
    practice_id: str | None = _UNSET,
    invoice_date: date | None = _UNSET,
    due_date: date | None = _UNSET,
    reference: str | None = _UNSET,
    notes: str | None = _UNSET,
    pension_enabled: bool = _UNSET,
    lines: Sequence[LineData] | None = _UNSET,
) -> Invoice:
    if inv is None:
        profile = core.get_profile(s)
        inv = Invoice(status=InvoiceStatus.draft, pension_enabled=profile.pension_default_enabled)
        s.add(inv)
        event = "created"
    else:
        _require_draft(inv)
        event = None
    if practice_id is not _UNSET:
        inv.practice = _practice(s, practice_id)
        inv.practice_id = practice_id
    if invoice_date is not _UNSET:
        inv.invoice_date = invoice_date
    if due_date is not _UNSET:
        inv.due_date = due_date
    if reference is not _UNSET:
        inv.reference = (reference or "").strip() or None
    if notes is not _UNSET:
        inv.notes = (notes or "").strip() or None
    if pension_enabled is not _UNSET:
        inv.pension_enabled = pension_enabled
    if lines is not _UNSET and lines is not None:
        _set_lines(inv, lines)
    _refresh_draft_cache(s, inv)
    s.flush()
    if event:
        s.add(InvoiceEvent(invoice_id=inv.id, event_type=event, metadata_json={}))
    s.commit()
    return inv


def delete_draft(s: Session, inv: Invoice) -> None:
    _require_draft(inv)
    from locuvi.services.diary import release_sessions

    release_sessions(s, inv.id)
    s.query(InvoiceEvent).filter(InvoiceEvent.invoice_id == inv.id).delete()
    s.delete(inv)
    s.commit()


def duplicate(s: Session, source: Invoice) -> Invoice:
    lines = [
        LineData(
            ln.service_date,
            ln.description,
            ln.unit,
            ln.quantity,
            ln.unit_price,
            ln.pensionable,
            ln.agreed_rate,
        )  # fmt: skip
        for ln in source.lines
    ]
    practice_id = source.practice_id
    if practice_id and (p := s.get(Practice, practice_id)) is not None and p.is_archived:
        practice_id = None
    inv = Invoice(
        status=InvoiceStatus.draft,
        pension_enabled=source.pension_enabled,
        reference=source.reference,
        notes=source.notes,
        duplicated_from_id=source.id,
    )
    s.add(inv)
    inv.practice = _practice(s, practice_id)
    inv.practice_id = practice_id
    _set_lines(inv, lines)
    _refresh_draft_cache(s, inv)
    s.flush()
    s.add(
        InvoiceEvent(
            invoice_id=inv.id, event_type="created", metadata_json={"duplicated_from": source.id}
        )
    )
    s.add(
        InvoiceEvent(
            invoice_id=source.id, event_type="duplicated", metadata_json={"new_draft": inv.id}
        )
    )
    s.commit()
    return inv


def split_by_month(s: Session, inv: Invoice) -> list[Invoice]:
    """Split a draft so each calendar month gets its own draft.

    The original draft keeps the earliest month; returns all resulting drafts.
    """
    _require_draft(inv)
    groups: dict[tuple[int, int], list[InvoiceLine]] = {}
    for ln in inv.lines:
        groups.setdefault((ln.service_date.year, ln.service_date.month), []).append(ln)
    if len(groups) <= 1:
        return [inv]
    keys = sorted(groups)
    result = [inv]
    for key in keys[1:]:
        new = Invoice(
            status=InvoiceStatus.draft,
            pension_enabled=inv.pension_enabled,
            reference=inv.reference,
            notes=inv.notes,
            invoice_date=inv.invoice_date,
            due_date=inv.due_date,
            practice_id=inv.practice_id,
        )
        new.practice = inv.practice
        s.add(new)
        _set_lines(
            new,
            [
                LineData(
                    ln.service_date,
                    ln.description,
                    ln.unit,
                    ln.quantity,
                    ln.unit_price,
                    ln.pensionable,
                    ln.agreed_rate,
                )
                for ln in groups[key]
            ],
        )
        _refresh_draft_cache(s, new)
        s.flush()
        s.add(
            InvoiceEvent(
                invoice_id=new.id, event_type="created", metadata_json={"split_from": inv.id}
            )
        )
        result.append(new)
    keep = [
        LineData(
            ln.service_date,
            ln.description,
            ln.unit,
            ln.quantity,
            ln.unit_price,
            ln.pensionable,
            ln.agreed_rate,
        )  # fmt: skip
        for ln in groups[keys[0]]
    ]
    _set_lines(inv, keep)
    _refresh_draft_cache(s, inv)
    s.add(
        InvoiceEvent(
            invoice_id=inv.id,
            event_type="split",
            metadata_json={"into": [x.id for x in result[1:]]},
        )
    )
    s.commit()
    return result


# ------------------------------------------------------------------------- snapshot


def _address_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def seller_block(profile: Any) -> dict[str, Any]:
    return {
        "legal_name": profile.legal_name,
        "trading_name": profile.trading_name,
        "designation": profile.designation,
        "address_lines": _address_lines(profile.address_lines),
        "postcode": profile.postcode,
        "email": profile.email,
        "phone": profile.phone,
    }


def build_snapshot(
    s: Session,
    inv: Invoice,
    a: Analysis,
    *,
    number: str | None,
    invoice_date: date | None,
    due_date: date | None,
    issued_at: datetime | None,
) -> dict[str, Any]:
    profile = core.get_profile(s)
    practice = inv.practice
    policy = a.policy
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "invoice": {
            "id": inv.id,
            "number": number,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "due_date": due_date.isoformat() if due_date else None,
            "work_start_date": a.work_start.isoformat() if a.work_start else None,
            "work_end_date": a.work_end.isoformat() if a.work_end else None,
            "reference": inv.reference,
            "notes": inv.notes,
            "currency": "GBP",
            "issued_at": issued_at.isoformat() if issued_at else None,
        },
        "seller": seller_block(profile),
        "bill_to": {
            "practice_id": practice.id if practice else None,
            "name": practice.name if practice else "",
            "address_lines": _address_lines(practice.billing_address) if practice else [],
            "contact_name": practice.contact_name if practice else None,
            "billing_email": practice.billing_email if practice else None,
            "reference": practice.reference if practice else None,
        },
        "bank": {
            "account_holder": profile.bank_account_holder,
            "sort_code": format_sort_code(profile.bank_sort_code),
            "account_number": profile.bank_account_number,
        },
        "lines": [
            {
                "service_date": ln.service_date.isoformat(),
                "description": ln.description,
                "unit": ln.unit,
                "quantity": str(ln.quantity),
                "unit_price": str(ln.unit_price),
                "amount": str(amount),
                "pensionable": ln.pensionable,
                **({"agreed_rate": str(ln.agreed_rate)} if ln.agreed_rate is not None else {}),
            }
            for ln, amount in zip(inv.lines, a.totals.line_amounts, strict=True)
        ],
        "totals": a.totals.as_strings(),
        "pension": {
            "enabled": inv.pension_enabled,
            "policy_id": policy.id if policy else None,
            "policy_label": policy.label if policy else None,
            "effective_from": policy.effective_from.isoformat() if policy else None,
            "pensionable_fraction": str(policy.pensionable_fraction) if policy else None,
            "employer_rate": str(policy.employer_rate) if policy else None,
            "rounding": ROUNDING_DESCRIPTION,
        },
        "vat": {"status": profile.vat_status, "amount": None},
        "presentation": branding.presentation(profile),
    }


def format_sort_code(raw: str) -> str:
    return f"{raw[0:2]}-{raw[2:4]}-{raw[4:6]}" if len(raw) == 6 else raw


def preview_pdf(s: Session, inv: Invoice) -> bytes:
    a = analyse(
        s,
        lines=inv.lines,
        pension_enabled=inv.pension_enabled,
        practice=inv.practice,
        reference=inv.reference,
    )
    if inv.status != InvoiceStatus.draft:
        raise Conflict("invoice.not_draft", "Use the issued PDF for issued invoices.")
    profile = core.get_profile(s)
    inv_date = inv.invoice_date or core.today_london()
    terms = _terms_days(inv, profile.payment_terms_days)
    due = inv.due_date or inv_date + timedelta(days=terms)
    snap = build_snapshot(
        s, inv, a, number=None, invoice_date=inv_date, due_date=due, issued_at=None
    )
    return render_invoice_pdf(snap, draft=True)


def _terms_days(inv: Invoice, default: int) -> int:
    if inv.practice is not None and inv.practice.default_payment_terms_days is not None:
        return inv.practice.default_payment_terms_days
    return default


# ---------------------------------------------------------------------------- issue


@dataclass
class IssueResult:
    invoice: Invoice
    replayed: bool


AfterIssueHook = Callable[[Session, Invoice], None]


def issue(
    settings: Settings,
    invoice_id: str,
    idempotency_key: str,
    *,
    after_issue: AfterIssueHook | None = None,
    render: Callable[[dict[str, Any]], bytes] = render_invoice_pdf,
) -> IssueResult:
    """Issue a draft in one durable operation.

    BEGIN IMMEDIATE serialises concurrent issues. The number, snapshot, PDF
    file and status change commit together; any failure (including PDF
    rendering) rolls back so the number is not consumed.
    """
    key = (idempotency_key or "").strip()
    if not (8 <= len(key) <= 100):
        raise DomainError("invoice.idempotency_key_required", "An idempotency key is required.")

    with db.immediate_session() as s:
        inv = get_invoice(s, invoice_id)
        if inv.status != InvoiceStatus.draft:
            if inv.issue_idempotency_key == key:
                return IssueResult(inv, replayed=True)
            raise Conflict(
                "invoice.already_issued",
                "This invoice has already been issued.",
                number=inv.invoice_number,
            )
        other = s.scalars(select(Invoice).where(Invoice.issue_idempotency_key == key)).first()
        if other is not None:
            raise Conflict("invoice.idempotency_key_reused", "Idempotency key already used.")

        a = analyse(
            s,
            lines=inv.lines,
            pension_enabled=inv.pension_enabled,
            practice=inv.practice,
            for_issue=True,
            reference=inv.reference,
        )
        if a.blocking:
            raise ValidationFailed([p.as_dict() for p in a.blocking])
        for ln, price in zip(inv.lines, a.unit_prices, strict=True):
            ln.unit_price = price  # inclusive rates converted with the rate in force

        profile = core.get_profile(s)
        seq = core.get_sequence(s)
        number = core.format_number(seq.prefix, seq.next_number, seq.padding)
        if s.scalars(select(Invoice.id).where(Invoice.invoice_number == number)).first():
            raise Conflict(
                "sequence.number_taken",
                f"Invoice number {number} is already used. Raise the next number in Settings.",
                number=number,
            )
        issued_at = utcnow()
        inv_date = inv.invoice_date or core.today_london(issued_at)
        due = inv.due_date or inv_date + timedelta(
            days=_terms_days(inv, profile.payment_terms_days)
        )
        if due < inv_date:
            raise DomainError("invoice.due_before_issue", "The due date is before the issue date.")

        snapshot = build_snapshot(
            s, inv, a, number=number, invoice_date=inv_date, due_date=due, issued_at=issued_at
        )
        pdf = render(snapshot)
        stored = write_issued_pdf(settings.data_dir, inv.id, pdf)

        for ln, amount in zip(inv.lines, a.totals.line_amounts, strict=True):
            ln.amount = amount
        t = a.totals
        inv.status = InvoiceStatus.issued
        inv.invoice_number = number
        inv.invoice_date = inv_date
        inv.due_date = due
        inv.work_start_date = a.work_start
        inv.work_end_date = a.work_end
        inv.fee_subtotal = t.fee_subtotal
        inv.pensionable_basic_total = t.pensionable_basic_total
        inv.pensionable_pay = t.pensionable_pay
        inv.employer_rate = t.employer_rate
        inv.employer_contribution = t.employer_contribution
        inv.vat_amount = None
        inv.grand_total = t.grand_total
        inv.pension_policy_id = a.policy.id if a.policy else None
        inv.issued_at = issued_at
        inv.immutable_snapshot_json = snapshot
        inv.local_pdf_path = stored.relative_path
        inv.local_pdf_sha256 = stored.sha256
        inv.local_pdf_size = stored.size
        inv.issue_idempotency_key = key
        seq.next_number += 1
        s.add(
            InvoiceEvent(
                invoice_id=inv.id,
                event_type="issued",
                metadata_json={"number": number, "pdf_sha256": stored.sha256},
            )
        )
        from locuvi.services.diary import reconcile_on_issue

        reconcile_on_issue(s, inv)
        if after_issue is not None:
            after_issue(s, inv)
        s.commit()
        log.info("invoice issued id=%s number=%s", inv.id, number)
        return IssueResult(inv, replayed=False)


def void(s: Session, inv: Invoice, reason: str) -> Invoice:
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("invoice.void_reason_required", "Give a reason for voiding.")
    if inv.status == InvoiceStatus.draft:
        raise Conflict("invoice.void_draft", "Drafts can be deleted instead of voided.")
    if inv.status == InvoiceStatus.voided:
        raise Conflict("invoice.already_voided", "This invoice is already void.")
    if inv.credit_notes:
        raise Conflict(
            "invoice.void_has_credits", "This invoice has credit notes; it can't be voided."
        )
    if inv.payments:
        raise Conflict(
            "invoice.void_has_payments",
            "This invoice has payments recorded. Remove them before voiding.",
        )
    from locuvi.services.diary import release_sessions

    release_sessions(s, inv.id)
    inv.status = InvoiceStatus.voided
    inv.voided_at = datetime.now(UTC)
    inv.void_reason = reason[:1000]
    s.add(InvoiceEvent(invoice_id=inv.id, event_type="voided", metadata_json={"reason": reason}))
    s.commit()
    return inv
