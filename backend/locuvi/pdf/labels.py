"""Keyed text for the invoice PDF (en-GB). Keys are stable for future locales."""

from __future__ import annotations

from typing import Any

EN_GB: dict[str, str] = {
    "pdf.invoice": "Invoice",
    "pdf.invoice_title": "INVOICE",
    "pdf.subject": "GP locum invoice",
    "pdf.draft_number": "DRAFT",
    "pdf.draft_watermark": "DRAFT – NOT AN INVOICE",
    "pdf.not_issued": "Not issued",
    "pdf.trading_as": "Trading as {name}",
    "pdf.invoice_number": "Invoice no.",
    "pdf.issue_date": "Issue date",
    "pdf.due_date": "Due date",
    "pdf.work_period": "Work period",
    "pdf.reference": "Reference",
    "pdf.bill_to": "Bill to",
    "pdf.attention": "FAO {name}",
    "pdf.col_date": "Date",
    "pdf.col_description": "Description",
    "pdf.col_pensionable": "NHS pens.",
    "pdf.col_qty": "Qty",
    "pdf.col_rate": "Rate",
    "pdf.col_amount": "Amount",
    "pdf.yes": "Yes",
    "pdf.no": "No",
    "pdf.basic_fee_excl": "Basic locum fee (pensionable, excl. employer pension addition)",
    "pdf.other_fees": "Other fees (non-pensionable)",
    "pdf.fee_subtotal": "Fee subtotal",
    "pdf.pensionable_pay_note": "Pensionable pay ({fraction} of {basic}) – for information",
    "pdf.employer_addition": "Employer NHS pension contribution ({rate} of pensionable pay)",
    "pdf.total_due": "Total due (GBP)",
    "pdf.vat_not_registered": "No VAT charged: supplier is not VAT registered.",
    "pdf.payment_details": "Payment details",
    "pdf.bank_holder": "Account name",
    "pdf.sort_code": "Sort code",
    "pdf.account_number": "Account number",
    "pdf.payment_reference": "Payment reference",
    "pdf.payment_due": "Payment due by",
    "pdf.notes": "Notes",
    "pdf.pension_footnote": (
        "The employer NHS pension contribution is the practice's employer contribution "
        "for pensionable GP locum work, added to the basic locum fee above. This invoice "
        "is not an NHS Pension Scheme form (GP Locum A/B)."
    ),
    "pdf.page_x_of_y": "Page {page} of {total}",
    "unit.am": "AM session",
    "unit.pm": "PM session",
    "unit.day": "full day",
    "unit.hours": "hours",
    "unit.custom": "",
}


def label(key: str, **params: Any) -> str:
    text = EN_GB.get(key, key)
    return text.format(**params) if params else text
