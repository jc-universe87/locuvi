"""Exact GBP arithmetic and the v0.1 fee / employer pension calculation.

Rules (specs/INVOICES_AND_PENSIONS.md):
  line amount            = quantity × unit price, ROUND_HALF_UP to 2dp
  eligible basic fee     = Σ amounts of pensionable lines
  pensionable pay        = eligible basic fee × pensionable fraction (0.90), HALF_UP 2dp
  employer contribution  = pensionable pay × employer rate (e.g. 0.1438), HALF_UP 2dp
  grand total            = fee subtotal + employer contribution (no VAT in v0.1)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")
ROUNDING_DESCRIPTION = "ROUND_HALF_UP to 0.01 GBP at each stage (line, pensionable pay, employer)"


class MoneyError(ValueError):
    pass


def to_decimal(value: object, *, field: str = "value") -> Decimal:
    if isinstance(value, float):
        # Floats are never accepted for money: their binary value is inexact.
        raise MoneyError(f"{field}: floats are not accepted, use a decimal string")
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MoneyError(f"{field}: not a valid decimal number") from exc
    if not d.is_finite():
        raise MoneyError(f"{field}: must be finite")
    return d


def round_money(value: Decimal) -> Decimal:
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def fmt_gbp(value: Decimal) -> str:
    """UK presentation, e.g. ``£1,234.50``; negative values as ``-£5.00``."""
    v = round_money(value)
    sign = "-" if v < 0 else ""
    return f"{sign}£{abs(v):,.2f}"


@dataclass(frozen=True)
class LineInput:
    service_date: date
    quantity: Decimal
    unit_price: Decimal
    pensionable: bool


@dataclass(frozen=True)
class PensionPolicyValues:
    effective_from: date
    pensionable_fraction: Decimal
    employer_rate: Decimal
    label: str = ""


@dataclass(frozen=True)
class Totals:
    line_amounts: tuple[Decimal, ...]
    fee_subtotal: Decimal
    non_pensionable_total: Decimal
    pensionable_basic_total: Decimal
    pensionable_pay: Decimal
    employer_rate: Decimal | None
    pensionable_fraction: Decimal | None
    employer_contribution: Decimal
    vat_amount: Decimal | None
    grand_total: Decimal

    def as_strings(self) -> dict[str, object]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "line_amounts": [str(a) for a in self.line_amounts],
            "fee_subtotal": s(self.fee_subtotal),
            "non_pensionable_total": s(self.non_pensionable_total),
            "pensionable_basic_total": s(self.pensionable_basic_total),
            "pensionable_pay": s(self.pensionable_pay),
            "employer_rate": s(self.employer_rate),
            "pensionable_fraction": s(self.pensionable_fraction),
            "employer_contribution": s(self.employer_contribution),
            "vat_amount": s(self.vat_amount),
            "grand_total": s(self.grand_total),
        }


def line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return round_money(quantity * unit_price)


def calculate_totals(
    lines: Iterable[LineInput],
    *,
    pension_enabled: bool,
    policy: PensionPolicyValues | None,
) -> Totals:
    lines = list(lines)
    amounts = tuple(line_amount(ln.quantity, ln.unit_price) for ln in lines)
    fee_subtotal = sum(amounts, ZERO)
    apply_pension = pension_enabled and policy is not None
    basic = (
        sum((a for a, ln in zip(amounts, lines, strict=True) if ln.pensionable), ZERO)
        if apply_pension
        else ZERO
    )
    if apply_pension and basic != ZERO:
        assert policy is not None
        pensionable_pay = round_money(basic * policy.pensionable_fraction)
        employer = round_money(pensionable_pay * policy.employer_rate)
    else:
        pensionable_pay = ZERO
        employer = ZERO
    return Totals(
        line_amounts=amounts,
        fee_subtotal=round_money(fee_subtotal),
        non_pensionable_total=round_money(fee_subtotal - basic),
        pensionable_basic_total=round_money(basic),
        pensionable_pay=pensionable_pay,
        employer_rate=policy.employer_rate if apply_pension and policy else None,
        pensionable_fraction=policy.pensionable_fraction if apply_pension and policy else None,
        employer_contribution=employer,
        vat_amount=None,
        grand_total=round_money(fee_subtotal + employer),
    )


def pensionable_months(lines: Iterable[LineInput]) -> list[tuple[int, int]]:
    """Distinct (year, month) calendar months of pensionable lines, sorted."""
    return sorted({(ln.service_date.year, ln.service_date.month) for ln in lines if ln.pensionable})


def select_policy(policies: Iterable[PensionPolicyValues], on: date) -> PensionPolicyValues | None:
    eligible = [p for p in policies if p.effective_from <= on]
    return max(eligible, key=lambda p: p.effective_from) if eligible else None
