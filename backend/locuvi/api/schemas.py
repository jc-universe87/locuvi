"""Pydantic request/response models. Money crosses the API as decimal strings."""

from __future__ import annotations

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
