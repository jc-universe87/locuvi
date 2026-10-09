"""A4 worksheet with the month's figures for GP Locum Forms A and B (not the official form)."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from locuvi.money import fmt_gbp
from locuvi.pdf.render import (
    MONTHS,
    RULE,
    STEEL,
    _esc,
    _NumberedCanvas,
    _register_fonts,
    _styles,
    short_date,
)


def _month_label(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{MONTHS[m - 1]} {y}"


def _pct(rate: str) -> str:
    return f"{(Decimal(rate) * 100).normalize():f}%"


def render_pension_worksheet(fig: dict[str, Any]) -> bytes:
    _register_fonts()
    st = _styles()
    buf = io.BytesIO()
    month = _month_label(fig["month"])
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=22 * mm,
        title=f"NHS pension worksheet {month}",
        creator="Locuvi",
    )
    width = A4[0] - 36 * mm
    locum = fig["locum"]
    story: list[Any] = [
        Paragraph("NHS pension worksheet", st["title"]),
        Paragraph(
            _esc(f"Forms A: work done in {month} · Form B: fees received in {month}"), st["right"]
        ),
        Spacer(1, 5 * mm),
        Paragraph(
            _esc(
                "Figures prepared by Locuvi from your issued invoices, to copy onto the official "
                "NHSBSA GP Locum A and B forms. Check them against current NHSBSA/PCSE "
                "guidance. This worksheet is not a submission."
            ),
            st["small"],
        ),
        Spacer(1, 5 * mm),
    ]
    who = [["Locum", locum.get("name") or ""]]
    if locum.get("professional_number"):
        who.append(["GMC number", locum["professional_number"]])
    if locum.get("pension_ref"):
        who.append(["Pension reference (SD)", locum["pension_ref"]])
    story.append(_kv(who, st, width))
    story.append(Spacer(1, 6 * mm))

    for i, a in enumerate(fig["forms_a"], 1):
        rows = [
            ["Practice", a["practice_name"]],
            ["Practice code", a.get("practice_code") or "—"],
            ["Session dates", ", ".join(short_date(d)[:5] for d in a["session_dates"])],
            ["Invoice", ", ".join(a["invoices"])],
            ["Submit within 10 weeks — by", short_date(a["deadline"])],
            ["Total locum fees (pensionable)", fmt_gbp(Decimal(a["fees"]))],
            ["Pensionable pay (90%)", fmt_gbp(Decimal(a["pensionable_pay"]))],
            ["Employer contribution (paid by practice)", fmt_gbp(Decimal(a["employer"]))],
        ]
        story.append(
            KeepTogether(
                [
                    Paragraph(f"FORM A {i} OF {len(fig['forms_a'])}", st["h"]),
                    _kv(rows, st, width),
                    Spacer(1, 6 * mm),
                ]
            )
        )

    if not fig["forms_a"]:
        story.append(Paragraph(_esc(f"No pensionable work done in {month}."), st["small"]))
        story.append(Spacer(1, 6 * mm))
    b = fig["form_b"]
    if b["items"]:
        items = [
            [
                f"{r['invoice_number']} · {r['practice']} · work {_month_label(r['work_month'])}",
                f"paid {short_date(r['paid_on'])}: pensionable pay "
                f"{fmt_gbp(Decimal(r['pensionable_pay']))}, employer "
                f"{fmt_gbp(Decimal(r['employer']))}",
            ]
            for r in b["items"]
        ]
        story.append(
            KeepTogether(
                [
                    Paragraph(f"FEES RECEIVED IN {month.upper()}", st["h"]),
                    _kv(items, st, width),
                    Spacer(1, 6 * mm),
                ]
            )
        )
    rows = [
        ["Forms A included", str(len({r["invoice_id"] for r in b["items"]}))],
        ["Total pensionable pay received", fmt_gbp(Decimal(b["pensionable_pay"]))],
        ["Employer contributions", fmt_gbp(Decimal(b["employer"]))],
    ]
    if b.get("employee") is not None:
        rows += [
            [
                f"Employee contributions ({_pct(b['employee_rate'])} tier)",
                fmt_gbp(Decimal(b["employee"])),
            ],
            ["Total contributions payable", fmt_gbp(Decimal(b["total_payable"]))],
        ]
    else:
        rows.append(["Employee contributions", "Set your tier rate in Settings → Pension"])
    rows.append(["Send Form B and contributions by", short_date(b["due_by"])])
    story.append(
        KeepTogether(
            [Paragraph("FORM B — FEES RECEIVED THIS MONTH", st["h"]), _kv(rows, st, width)]
        )
    )

    def canvasmaker(*args: Any, **kwargs: Any) -> _NumberedCanvas:
        c = _NumberedCanvas(*args, **kwargs)
        c.footer_left = f"{locum.get('name') or ''} · NHS pension worksheet {month}"
        return c

    doc.build(story, canvasmaker=canvasmaker)
    return buf.getvalue()


def _kv(rows: list[list[str]], st: dict[str, Any], width: float) -> Table:
    return Table(
        [[Paragraph(_esc(k), st["muted"]), Paragraph(_esc(v), st["base"])] for k, v in rows],
        colWidths=[70 * mm, width - 70 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Inter"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, STEEL),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ]
        ),
        hAlign="LEFT",
    )
