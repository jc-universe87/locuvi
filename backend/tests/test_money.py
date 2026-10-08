import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from locuvi.money import (
    LineInput,
    MoneyError,
    PensionPolicyValues,
    calculate_totals,
    fmt_gbp,
    pensionable_months,
    round_money,
    select_policy,
    to_decimal,
)

POLICY = PensionPolicyValues(date(2026, 4, 1), Decimal("0.90"), Decimal("0.1438"))
FIXTURE = Path(__file__).parents[2] / "docs" / "handover" / "invoice-fixture.json"


def L(price, qty="1", pensionable=True, d=date(2026, 10, 8)):  # noqa: N802
    return LineInput(d, Decimal(qty), Decimal(price), pensionable)


def test_handover_fixture_600():
    fx = json.loads(FIXTURE.read_text())["invoice"]
    lines = [L(e["unit_rate"], e["quantity"], e["pensionable"]) for e in fx["entries"]]
    t = calculate_totals(lines, pension_enabled=True, policy=POLICY)
    exp = fx["expected"]
    assert str(t.pensionable_basic_total) == exp["basic_fee"]
    assert str(t.pensionable_pay) == exp["pensionable_pay"]
    assert str(t.employer_rate) == exp["employer_rate"]
    assert str(t.employer_contribution) == exp["employer_contribution"]
    assert str(t.grand_total) == exp["total"]


def test_non_pensionable_line_excluded():
    t = calculate_totals([L("600.00"), L("150.00", pensionable=False)],
                         pension_enabled=True, policy=POLICY)
    assert t.fee_subtotal == Decimal("750.00")
    assert t.pensionable_basic_total == Decimal("600.00")
    assert t.non_pensionable_total == Decimal("150.00")
    assert t.employer_contribution == Decimal("77.65")
    assert t.grand_total == Decimal("827.65")


def test_pension_switched_off():
    t = calculate_totals([L("600.00")], pension_enabled=False, policy=POLICY)
    assert t.employer_contribution == Decimal("0.00")
    assert t.employer_rate is None
    assert t.grand_total == Decimal("600.00")


def test_differing_rates_and_hours():
    lines = [L("600.00", d=date(2026, 10, 1)), L("85.50", "3.5", d=date(2026, 10, 2)),
             L("550.00", d=date(2026, 10, 3))]
    t = calculate_totals(lines, pension_enabled=True, policy=POLICY)
    assert t.line_amounts == (Decimal("600.00"), Decimal("299.25"), Decimal("550.00"))
    assert t.fee_subtotal == Decimal("1449.25")
    # 1449.25 * 0.9 = 1304.325 -> 1304.33 ; * 0.1438 = 187.562654 -> 187.56
    assert t.pensionable_pay == Decimal("1304.33")
    assert t.employer_contribution == Decimal("187.56")
    assert t.grand_total == Decimal("1636.81")


@pytest.mark.parametrize(
    "qty,price,expected",
    [("0.5", "0.01", "0.01"), ("0.5", "0.03", "0.02"), ("1.25", "10.10", "12.63"),
     ("3", "33.33", "99.99")],
)
def test_line_rounding_half_up(qty, price, expected):
    t = calculate_totals([L(price, qty)], pension_enabled=False, policy=None)
    assert t.line_amounts[0] == Decimal(expected)


def test_half_up_at_each_stage():
    # basic 0.05 -> pay 0.045 -> 0.05 (half up) ; employer 0.05*0.1438=0.00719 -> 0.01
    t = calculate_totals([L("0.05")], pension_enabled=True, policy=POLICY)
    assert t.pensionable_pay == Decimal("0.05")
    assert t.employer_contribution == Decimal("0.01")


def test_split_invoices_sum_reasonably():
    whole = calculate_totals([L("600.00"), L("600.00")], pension_enabled=True, policy=POLICY)
    part = calculate_totals([L("600.00")], pension_enabled=True, policy=POLICY)
    assert whole.employer_contribution == Decimal("155.30")  # 1080 * .1438 = 155.304
    assert part.employer_contribution * 2 == Decimal("155.30")


def test_rejects_float():
    with pytest.raises(MoneyError):
        to_decimal(0.1)
    assert to_decimal("0.10") == Decimal("0.10")


def test_formatting():
    assert fmt_gbp(Decimal("1234.5")) == "£1,234.50"
    assert fmt_gbp(Decimal("-5")) == "-£5.00"
    assert round_money(Decimal("2.675")) == Decimal("2.68")


def test_months_and_policy_selection():
    lines = [L("1", d=date(2026, 10, 31)), L("1", d=date(2026, 11, 1)),
             L("1", pensionable=False, d=date(2026, 12, 1))]
    assert pensionable_months(lines) == [(2026, 10), (2026, 11)]
    newer = PensionPolicyValues(date(2027, 4, 1), Decimal("0.90"), Decimal("0.15"))
    assert select_policy([POLICY, newer], date(2027, 3, 31)) is POLICY
    assert select_policy([POLICY, newer], date(2027, 4, 1)) is newer
    assert select_policy([POLICY], date(2026, 3, 31)) is None
