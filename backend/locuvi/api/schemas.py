"""Pydantic request/response models. Money crosses the API as decimal strings."""

from __future__ import annotations

import datetime as _dt
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from locuvi.money import MoneyError, to_decimal


def _dec(v: str) -> str:
    try:
        to_decimal(v)
    except MoneyError as exc:
        raise ValueError(str(exc)) from None
    return v.strip()


DecStr = Annotated[str, StringConstraints(max_length=20), AfterValidator(_dec)]
Short = Annotated[str, StringConstraints(max_length=200)]
Text = Annotated[str, StringConstraints(max_length=2000)]
Unit = Literal["am", "pm", "day", "hours", "custom"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------- settings


def _digits(v: str | None, n: int, name: str) -> str | None:
    if v is None:
        return None
    d = re.sub(r"[\s-]", "", v)
    if d and (not d.isdigit() or len(d) != n):
        raise ValueError(f"{name} must be {n} digits")
    return d


class ProfileIn(Strict):
    legal_name: Short = ""
    trading_name: Short | None = None
    designation: Short = ""
    address_lines: Text = ""
    postcode: Annotated[str, StringConstraints(max_length=20)] = ""
    email: Short = ""
    phone: Annotated[str, StringConstraints(max_length=50)] | None = None
    bank_account_holder: Short = ""
    bank_sort_code: Annotated[str, AfterValidator(lambda v: _digits(v, 6, "Sort code"))] = ""
    bank_account_number: (
        Annotated[str, AfterValidator(lambda v: _digits(v, 8, "Account number"))] | None
    ) = Field(default=None, description="Omit or null to keep the saved number")
    vat_status: Literal["not_vat_registered", "vat_registered"] = "not_vat_registered"
    payment_terms_days: Annotated[int, Field(ge=0, le=365)] = 30
    pension_default_enabled: bool = True
    professional_number: Annotated[str, StringConstraints(max_length=40)] | None = None
    pension_ref: Annotated[str, StringConstraints(max_length=40)] | None = None
    employee_rate: DecStr | None = None
    setup_completed: bool | None = None
    digest_enabled: bool | None = None


class ProfileOut(BaseModel):
    legal_name: str
    trading_name: str | None
    designation: str
    address_lines: str
    postcode: str
    email: str
    phone: str | None
    bank_account_holder: str
    bank_sort_code: str
    bank_account_number_masked: str
    bank_account_number_set: bool
    vat_status: str
    payment_terms_days: int
    pension_default_enabled: bool
    professional_number: str | None
    pension_ref: str | None
    employee_rate: str | None
    setup_completed: bool
    digest_enabled: bool
    last_digest_sent_at: str | None


class NumberingIn(Strict):
    prefix: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$")]
    next_number: Annotated[int, Field(ge=1, le=99_999_999)]
    padding: Annotated[int, Field(ge=1, le=8)] = 4


class NumberingOut(BaseModel):
    prefix: str
    next_number: int
    padding: int
    preview: str


class PolicyIn(Strict):
    effective_from: date
    employer_rate: DecStr
    pensionable_fraction: DecStr = "0.90"
    label: Short = ""
    source_note: Text = ""


class PolicyOut(BaseModel):
    id: str
    effective_from: date
    employer_rate: str
    pensionable_fraction: str
    label: str
    source_note: str
    in_use: bool


# -------------------------------------------------------------------- practices


class PracticeIn(Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    billing_address: Text = ""
    billing_email: Short | None = None
    contact_name: Short | None = None
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None
    default_rate: DecStr | None = None
    default_unit: Unit = "am"
    default_pensionable: bool = True
    rate_includes_pension: bool = False
    default_payment_terms_days: Annotated[int, Field(ge=0, le=365)] | None = None
    is_archived: bool = False
    practice_code: Annotated[str, StringConstraints(max_length=20)] | None = None
    po_required: bool = False
    invoice_instructions: Annotated[str, StringConstraints(max_length=2000)] | None = None
    form_a_signatory: Short | None = None


class PracticePatch(Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    billing_address: Text | None = None
    billing_email: Short | None = None
    contact_name: Short | None = None
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None
    default_rate: DecStr | None = None
    default_unit: Unit | None = None
    default_pensionable: bool | None = None
    rate_includes_pension: bool | None = None
    default_payment_terms_days: Annotated[int, Field(ge=0, le=365)] | None = None
    is_archived: bool | None = None
    practice_code: Annotated[str, StringConstraints(max_length=20)] | None = None
    po_required: bool | None = None
    invoice_instructions: Annotated[str, StringConstraints(max_length=2000)] | None = None
    form_a_signatory: Short | None = None


class PracticeOut(BaseModel):
    id: str
    name: str
    billing_address: str
    billing_email: str | None
    contact_name: str | None
    reference: str | None
    default_rate: str | None
    default_unit: str
    default_pensionable: bool
    rate_includes_pension: bool
    default_payment_terms_days: int | None
    is_archived: bool
    practice_code: str | None
    po_required: bool
    invoice_instructions: str | None
    form_a_signatory: str | None


# --------------------------------------------------------------------- invoices


class LineIn(Strict):
    service_date: date
    description: Annotated[str, StringConstraints(max_length=300)] = ""
    unit: Unit = "am"
    quantity: DecStr = "1"
    unit_price: DecStr
    pensionable: bool = False

    def as_decimals(self) -> tuple[Decimal, Decimal]:
        return Decimal(self.quantity), Decimal(self.unit_price)


class InvoiceIn(Strict):
    practice_id: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None
    notes: Text | None = None
    pension_enabled: bool | None = None
    lines: list[LineIn] | None = None


class CalculateIn(Strict):
    practice_id: str | None = None
    pension_enabled: bool = True
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None
    lines: list[LineIn] = []


class VoidIn(Strict):
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class WebDavIn(Strict):
    enabled: bool
    target_url: Annotated[str, StringConstraints(max_length=500)] = ""
    username: Short = ""
    base_path: Annotated[str, StringConstraints(max_length=300)] = "Locuvi/Invoices"
    auto_upload: bool = True
    password: Annotated[str, StringConstraints(max_length=500)] | None = Field(
        default=None, description="Omit/null keeps the saved password; empty string clears it"
    )


class WebDavTestIn(Strict):
    target_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    username: Short | None = None
    base_path: Annotated[str, StringConstraints(max_length=300)] | None = None
    password: Annotated[str, StringConstraints(max_length=500)] | None = None


class LoginIn(Strict):
    password: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class Page(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class SessionIn(Strict):
    practice_id: str
    date: _dt.date
    unit: Unit = "am"
    quantity: DecStr | None = None
    rate: DecStr | None = None
    pensionable: bool | None = None
    description: Annotated[str, StringConstraints(max_length=300)] | None = None


class SessionsIn(Strict):
    sessions: Annotated[list[SessionIn], Field(min_length=1, max_length=62)]


class SessionPatch(Strict):
    date: _dt.date | None = None
    unit: Unit | None = None
    quantity: DecStr | None = None
    rate: DecStr | None = None
    pensionable: bool | None = None
    description: Annotated[str, StringConstraints(max_length=300)] | None = None
    status: Literal["active", "cancelled"] | None = None


class InvoiceMonthIn(Strict):
    practice_id: str
    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")]


class PaymentIn(Strict):
    amount: DecStr | None = None
    paid_on: date | None = None
    method: Literal["bank_transfer", "cheque", "cash", "other"] = "bank_transfer"
    reference: Annotated[str, StringConstraints(max_length=100)] | None = None


class EmailConfigIn(Strict):
    enabled: bool = False
    host: Annotated[str, StringConstraints(max_length=200)] = ""
    port: Annotated[int, Field(ge=1, le=65535)] = 587
    security: Literal["starttls", "ssl"] = "starttls"
    username: Short = ""
    password: Annotated[str, StringConstraints(max_length=500)] | None = None
    from_address: Short = ""
    from_name: Short = ""
    bcc_self: bool = True


class EmailSendIn(Strict):
    to: Annotated[str, StringConstraints(min_length=3, max_length=500)]
    subject: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(max_length=10000)]


class PensionSubmitIn(Strict):
    submitted_on: date | None = None


class DismissIn(Strict):
    days: Annotated[int, Field(ge=1, le=365)] = 7


# ------------------------------------------------------------ inbox & assistant

DocKind = Literal["booking", "remittance", "statement", "pension", "other"]


class PasteIn(Strict):
    text: Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
    kind: DocKind | None = None


class DocumentPatch(Strict):
    kind: DocKind | None = None
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    status: Literal["new", "done"] | None = None
    practice_id: Annotated[str, StringConstraints(max_length=36)] | None = None


class AssistantIn(Strict):
    enabled: bool = False
    api_key: Annotated[str, StringConstraints(max_length=500)] | None = None
    clear_key: bool = False


class ProposalChoice(Strict):
    index: Annotated[int, Field(ge=0, le=100)]
    practice_id: Annotated[str, StringConstraints(max_length=36)] | None = None
    date: _dt.date | None = None
    unit: Literal["am", "pm", "day", "hours"] | None = None
    hours: DecStr | None = None
    rate: DecStr | None = None


class ProposalAcceptIn(Strict):
    items: Annotated[list[ProposalChoice], Field(min_length=1, max_length=62)]


class MailboxIn(Strict):
    enabled: bool = False
    host: Annotated[str, StringConstraints(max_length=200)] = ""
    port: Annotated[int, Field(ge=1, le=65535)] = 993
    security: Literal["ssl", "starttls"] = "ssl"
    username: Short = ""
    password: Annotated[str, StringConstraints(max_length=500)] | None = None
    folders: Annotated[
        list[Annotated[str, StringConstraints(max_length=300)]], Field(max_length=20)
    ] = []
    since_days: Annotated[int, Field(ge=1, le=730)] = 90
    auto_scan: bool = True


class BankAcceptIn(Strict):
    invoice_ids: (
        Annotated[
            list[Annotated[str, StringConstraints(max_length=36)]],
            Field(min_length=1, max_length=10),
        ]
        | None
    ) = None
