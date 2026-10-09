"""A4 invoice PDF rendered purely from an immutable snapshot dict.

The issued PDF is generated once at issue time and stored; it is never
regenerated for an issued invoice. Draft previews use the same template with a
watermark and no invoice number.
"""

from __future__ import annotations

import base64
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from locuvi.money import fmt_gbp
from locuvi.pdf.labels import label

FONT_DIR = Path(__file__).parent / "fonts"
INK = colors.HexColor("#1B2A33")
MUTED = colors.HexColor("#56656F")
STEEL = colors.HexColor("#294D63")
RULE = colors.HexColor("#D5DDE2")
ZEBRA = colors.HexColor("#F5F7F8")

_fonts_registered = False


def _register_fonts() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont("Inter", str(FONT_DIR / "Inter-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Inter-SemiBold", str(FONT_DIR / "Inter-SemiBold.ttf")))
    pdfmetrics.registerFont(TTFont("Inter-Bold", str(FONT_DIR / "Inter-Bold.ttf")))
    pdfmetrics.registerFontFamily(
        "Inter", normal="Inter", bold="Inter-Bold", italic="Inter", boldItalic="Inter-Bold"
    )
    _fonts_registered = True


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def uk_date(value: str | date | None) -> str:
    if not value:
        return ""
    d = value if isinstance(value, date) else date.fromisoformat(value)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def uk_period(start: str, end: str | None) -> str:
    """Compact range: '8–15 October 2026', '30 October – 2 November 2026'."""
    a = date.fromisoformat(start)
    b = date.fromisoformat(end) if end else a
    if a == b:
        return uk_date(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {MONTHS[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day} {MONTHS[a.month - 1]} – {uk_date(b)}"
    return f"{uk_date(a)} – {uk_date(b)}"


def short_date(value: str) -> str:
    d = date.fromisoformat(value)
    return d.strftime("%d/%m/%Y")


def _esc(text: str | None) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
    )


def _qty(value: str) -> str:
    d = Decimal(value).normalize()
    return f"{d:f}"


def _pct(rate: str) -> str:
    return f"{(Decimal(rate) * 100).normalize():f}%"


class _NumberedCanvas(rl_canvas.Canvas):
    """Two-pass canvas so every page can show 'Page X of Y' and the footer."""

    footer_left = ""
    footer_lines: list[str] = []
    watermark: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("invariant", 1)
        kwargs.setdefault("initialFontName", "Inter")
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (ReportLab API)
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_page_chrome(total)
            super().showPage()
        super().save()

    def _draw_page_chrome(self, total: int) -> None:
        width, _ = A4
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(18 * mm, 16 * mm, width - 18 * mm, 16 * mm)
        self.setFont("Inter", 7.5)
        self.setFillColor(MUTED)
        base = 8.5 * mm if self.footer_lines else 11 * mm
        self.drawString(18 * mm, base, self.footer_left)
        self.drawRightString(
            width - 18 * mm,
            base,
            label("pdf.page_x_of_y", page=self._pageNumber, total=total),
        )
        for text in self.footer_lines[:1]:  # the owner's own line, just under the rule
            self.drawCentredString(width / 2, 12.5 * mm, text)
        if self.watermark:
            self.setFont("Inter-Bold", 54)
            self.setFillColor(colors.Color(0.55, 0.35, 0.41, alpha=0.13))
            self.translate(width / 2, 148 * mm)
            self.rotate(35)
            self.drawCentredString(0, 0, self.watermark)
        self.restoreState()


def _accent(value: Any) -> colors.Color:
    """Accent from the snapshot: only a plain #RRGGBB is accepted, else the default."""
    if isinstance(value, str) and len(value) == 7 and value[0] == "#":
        try:
            int(value[1:], 16)
            return colors.HexColor(value)
        except ValueError:
            pass
    return STEEL


LOGO_MAX_W, LOGO_MAX_H = 60 * mm, 22 * mm


def _logo(b64: Any) -> Image | None:
    """The frozen logo, scaled to fit 60 x 22 mm, keeping its proportions."""
    if not isinstance(b64, str) or not b64:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
        w, h = ImageReader(io.BytesIO(data)).getSize()
    except (ValueError, OSError):
        return None
    scale = min(LOGO_MAX_W / w, LOGO_MAX_H / h)
    img = Image(io.BytesIO(data), width=w * scale, height=h * scale)
    img.hAlign = "LEFT"
    return img


def _svg_logo(svg: Any) -> Any:
    """The frozen vector logo (already cleaned on upload), scaled into the same box."""
    if not isinstance(svg, str) or not svg:
        return None
    from svglib.svglib import svg2rlg

    try:
        d = svg2rlg(io.BytesIO(svg.encode()))
    except Exception:  # noqa: BLE001 - a logo must never stop an invoice rendering
        return None
    if d is None or not d.width or not d.height:
        return None
    scale = min(LOGO_MAX_W / d.width, LOGO_MAX_H / d.height)
    d.scale(scale, scale)
    d.width, d.height = d.width * scale, d.height * scale
    d.hAlign = "LEFT"
    return d


def _styles(accent: colors.Color = STEEL) -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Inter", fontSize=9, leading=12.5, textColor=INK)
    return {
        "base": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=MUTED, fontSize=8.5),
        "small": ParagraphStyle("small", parent=base, textColor=MUTED, fontSize=7.5, leading=10),
        "seller": ParagraphStyle(
            "seller", parent=base, fontName="Inter-SemiBold", fontSize=12.5, leading=16
        ),
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontName="Inter-SemiBold",
            fontSize=22,
            leading=26,
            textColor=accent,
            alignment=TA_RIGHT,
        ),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "h": ParagraphStyle(
            "h",
            parent=base,
            fontName="Inter-SemiBold",
            fontSize=8,
            textColor=MUTED,
            leading=11,
            spaceAfter=2,
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11),
        "cellr": ParagraphStyle("cellr", parent=base, fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "th": ParagraphStyle(
            "th",
            parent=base,
            fontName="Inter-SemiBold",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_LEFT,
        ),
        "thr": ParagraphStyle(
            "thr",
            parent=base,
            fontName="Inter-SemiBold",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_RIGHT,
        ),
        "total": ParagraphStyle(
            "total", parent=base, fontName="Inter-Bold", fontSize=11, leading=14, alignment=TA_RIGHT
        ),
        "totall": ParagraphStyle(
            "totall", parent=base, fontName="Inter-Bold", fontSize=11, leading=14
        ),
    }


def render_invoice_pdf(snapshot: dict[str, Any], *, draft: bool = False) -> bytes:
    _register_fonts()
    look = snapshot.get("presentation") or {}
    accent = _accent(look.get("accent"))
    st = _styles(accent)
    inv = snapshot["invoice"]
    seller = snapshot["seller"]
    bill = snapshot["bill_to"]
    bank = snapshot["bank"]
    totals = snapshot["totals"]
    pension = snapshot["pension"]
    number = inv.get("number") or label("pdf.draft_number")
    credit = snapshot.get("credit") if snapshot.get("kind") == "credit_note" else None
    doc_label = label("pdf.credit_note") if credit else label("pdf.invoice")

    width = A4[0] - 36 * mm
    footer_text = look.get("footer") if isinstance(look.get("footer"), str) else ""
    footer_lines = simpleSplit(footer_text.strip(), "Inter", 7.5, width)
    if len(footer_lines) > 1:  # one line only: never pushes the invoice onto another page
        footer_lines = [footer_lines[0].rstrip() + "…"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=14 * mm,
        bottomMargin=22 * mm,
        title=f"{doc_label} {number}",
        author=seller.get("legal_name", ""),
        subject=label("pdf.subject"),
        creator="Locuvi",
    )

    # Header: seller (left) and title/meta (right)
    seller_lines = [f"<font name='Inter-SemiBold' size='12.5'>{_esc(seller['legal_name'])}</font>"]
    if seller.get("trading_name"):
        seller_lines.append(_esc(label("pdf.trading_as", name=seller["trading_name"])))
    if seller.get("designation"):
        seller_lines.append(f"<font color='#56656F'>{_esc(seller['designation'])}</font>")
    seller_lines += [_esc(x) for x in seller.get("address_lines", [])]
    if seller.get("postcode"):
        seller_lines.append(_esc(seller["postcode"]))
    contact = [c for c in (seller.get("email"), seller.get("phone")) if c]
    if contact:
        seller_lines.append(_esc(" · ".join(contact)))
    seller_par: Any = Paragraph("<br/>".join(seller_lines), st["base"])
    logo = _svg_logo(look.get("logo_svg")) or _logo(look.get("logo_png_b64"))
    if logo is not None:
        seller_par = [logo, Spacer(1, 3 * mm), seller_par]

    if credit:
        meta_rows = [
            [label("pdf.credit_number"), number],
            [label("pdf.credit_date"), uk_date(inv.get("invoice_date"))],
            [label("pdf.credits_invoice"), credit["invoice_number"]],
            [label("pdf.original_date"), uk_date(credit.get("invoice_date"))],
        ]
    else:
        meta_rows = [
            [label("pdf.invoice_number"), number],
            [label("pdf.issue_date"), uk_date(inv.get("invoice_date")) or label("pdf.not_issued")],
            [label("pdf.due_date"), uk_date(inv.get("due_date"))],
        ]
    if inv.get("work_start_date") and not credit:
        meta_rows.append(
            [label("pdf.work_period"), uk_period(inv["work_start_date"], inv.get("work_end_date"))]
        )
    if inv.get("reference") and not credit:
        meta_rows.append([label("pdf.reference"), inv["reference"]])
    meta = Table(
        [[Paragraph(_esc(k), st["muted"]), Paragraph(_esc(v), st["right"])] for k, v in meta_rows],
        colWidths=[30 * mm, 48 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Inter"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ]
        ),
    )
    title_text = label("pdf.credit_title") if credit else label("pdf.invoice_title")
    right_col = [Paragraph(title_text, st["title"]), Spacer(1, 4 * mm), meta]
    header = Table(
        [[seller_par, right_col]],
        colWidths=[width - 80 * mm, 80 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Inter"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )

    story: list[Any] = [
        header,
        Spacer(1, 4 * mm),
        HRFlowable(width="100%", thickness=1.2, color=accent, spaceAfter=4 * mm),
    ]

    bill_lines = [f"<font name='Inter-SemiBold'>{_esc(bill['name'])}</font>"]
    if bill.get("contact_name"):
        bill_lines.append(_esc(label("pdf.attention", name=bill["contact_name"])))
    bill_lines += [_esc(x) for x in bill.get("address_lines", [])]
    if bill.get("billing_email"):
        bill_lines.append(_esc(bill["billing_email"]))
    story += [
        Paragraph(label("pdf.bill_to").upper(), st["h"]),
        Paragraph("<br/>".join(bill_lines), st["base"]),
        Spacer(1, 5 * mm),
    ]

    # Line items
    pension_on = bool(pension.get("enabled"))
    head = [
        Paragraph(label("pdf.col_date"), st["th"]),
        Paragraph(label("pdf.col_description"), st["th"]),
        Paragraph(label("pdf.col_qty"), st["thr"]),
        Paragraph(label("pdf.col_rate"), st["thr"]),
        Paragraph(label("pdf.col_amount"), st["thr"]),
    ]
    if pension_on:
        head.insert(2, Paragraph(label("pdf.col_pensionable"), st["th"]))
    rows: list[list[Any]] = [head]
    for ln in snapshot["lines"]:
        desc = _esc(ln["description"])
        qty = _qty(ln["quantity"])
        if ln["unit"] == "hours":
            qty = label("pdf.qty_hours", qty=qty)
        row = [
            Paragraph(short_date(ln["service_date"]), st["cell"]),
            Paragraph(desc, st["cell"]),
            Paragraph(qty, st["cellr"]),
            Paragraph(fmt_gbp(Decimal(ln["unit_price"])), st["cellr"]),
            Paragraph(fmt_gbp(Decimal(ln["amount"])), st["cellr"]),
        ]
        if pension_on:
            row.insert(
                2,
                Paragraph(label("pdf.yes") if ln["pensionable"] else label("pdf.no"), st["cell"]),
            )
        rows.append(row)
    if pension_on:
        col_w = [
            22 * mm,
            width - 22 * mm - 20 * mm - 14 * mm - 24 * mm - 26 * mm,
            20 * mm,
            14 * mm,
            24 * mm,
            26 * mm,
        ]
    else:
        col_w = [22 * mm, width - 22 * mm - 14 * mm - 24 * mm - 26 * mm, 14 * mm, 24 * mm, 26 * mm]
    line_style = [
        ("FONTNAME", (0, 0), (-1, -1), "Inter"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, accent),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(2, len(rows), 2):
        line_style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    story.append(Table(rows, colWidths=col_w, repeatRows=1, style=TableStyle(line_style)))
    story.append(Spacer(1, 4 * mm))

    # Totals (kept together so they never orphan onto a page alone)
    trows: list[tuple[str, str, str]] = []
    basic = Decimal(totals["pensionable_basic_total"])
    other = Decimal(totals["non_pensionable_total"])
    if pension_on and basic > 0:
        trows.append(("base", label("pdf.basic_fee_excl"), fmt_gbp(basic)))
        if other > 0:
            trows.append(("base", label("pdf.other_fees"), fmt_gbp(other)))
    trows.append(("base", label("pdf.fee_subtotal"), fmt_gbp(Decimal(totals["fee_subtotal"]))))
    if pension_on and basic > 0:
        trows.append(
            (
                "muted",
                label(
                    "pdf.pensionable_pay_note",
                    fraction=_pct(totals["pensionable_fraction"]),
                    basic=fmt_gbp(basic),
                ),
                fmt_gbp(Decimal(totals["pensionable_pay"])),
            )
        )
        trows.append(
            (
                "base",
                label("pdf.employer_addition", rate=_pct(totals["employer_rate"])),
                fmt_gbp(Decimal(totals["employer_contribution"])),
            )
        )
    tdata = [
        [
            Paragraph(_esc(t), st["muted"] if kind == "muted" else st["base"]),
            Paragraph(v, st["right"]),
        ]
        for kind, t, v in trows
    ]
    tdata.append(
        [
            Paragraph(label("pdf.total_credited" if credit else "pdf.total_due"), st["totall"]),
            Paragraph(fmt_gbp(Decimal(totals["grand_total"])), st["total"]),
        ]
    )
    tot_w = 98 * mm
    totals_table = Table(
        tdata,
        colWidths=[tot_w - 30 * mm, 30 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Inter"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, accent),
                ("TOPPADDING", (0, -1), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        ),
        hAlign="RIGHT",
    )
    vat_note = Paragraph(_esc(label("pdf.vat_not_registered")), st["small"])

    pay_rows = [
        [label("pdf.bank_holder"), bank.get("account_holder", "")],
        [label("pdf.sort_code"), bank.get("sort_code", "")],
        [label("pdf.account_number"), bank.get("account_number", "")],
        [label("pdf.payment_reference"), number],
        [label("pdf.payment_due"), uk_date(inv.get("due_date"))],
    ]
    pay = Table(
        [[Paragraph(_esc(k), st["muted"]), Paragraph(_esc(v), st["base"])] for k, v in pay_rows],
        colWidths=[38 * mm, 60 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Inter"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
            ]
        ),
        hAlign="LEFT",
    )
    pension_note = (
        Paragraph(
            _esc(label("pdf.pension_footnote_credit" if credit else "pdf.pension_footnote")),
            st["small"],
        )
        if pension_on and basic > 0
        else None
    )
    inclusive_note = None
    agreed = sorted(
        {
            (ln["agreed_rate"], ln.get("unit") == "hours")
            for ln in snapshot.get("lines", [])
            if ln.get("agreed_rate") and ln.get("pensionable")
            and ln.get("agreed_rate") != ln.get("unit_price")
        }
    )  # fmt: skip
    if agreed and pension_on and basic > 0 and not credit:
        fraction = Decimal(str(pension.get("pensionable_fraction") or "0"))
        rate = Decimal(str(pension.get("employer_rate") or "0"))
        rates = ", ".join(
            label("pdf.per_hour" if hourly else "pdf.per_session", amount=fmt_gbp(Decimal(a)))
            for a, hourly in agreed
        )
        divisor = f"{(1 + fraction * rate).normalize():f}"
        text = label("pdf.inclusive_note", rates=rates, divisor=divisor,
                     fraction=_pct(str(fraction)), rate=_pct(str(rate)))  # fmt: skip
        inclusive_note = Paragraph(_esc(text), st["small"])
    closing: list[Any] = [
        totals_table,
        Spacer(1, 2 * mm),
        Table(
            [
                [vat_note],
                *([[inclusive_note]] if inclusive_note else []),
                *([[pension_note]] if pension_note else []),
            ],  # fmt: skip
            colWidths=[tot_w],
            hAlign="RIGHT",
            style=TableStyle(
                [("FONTNAME", (0, 0), (-1, -1), "Inter"), ("LEFTPADDING", (0, 0), (-1, -1), 3)]
            ),
        ),
    ]
    if credit:
        closing += [
            Spacer(1, 5 * mm),
            Paragraph(label("pdf.credit_reason_h").upper(), st["h"]),
            Paragraph(_esc(credit.get("reason", "")), st["base"]),
            Spacer(1, 3 * mm),
            Paragraph(
                _esc(label("pdf.credit_effect", invoice=credit["invoice_number"])), st["small"]
            ),
        ]
    else:
        closing += [
            Spacer(1, 5 * mm),
            Paragraph(label("pdf.payment_details").upper(), st["h"]),
            pay,
        ]
    story.append(KeepTogether(closing))

    if inv.get("notes"):
        story += [
            Spacer(1, 4 * mm),
            KeepTogether(
                [
                    Paragraph(label("pdf.notes").upper(), st["h"]),
                    Paragraph(_esc(inv["notes"]), st["base"]),
                ]
            ),
        ]

    footer = seller.get("legal_name", "")
    footer_left = f"{footer} · {doc_label} {number}" if footer else number
    watermark = label("pdf.draft_watermark") if draft else None

    def canvasmaker(*args: Any, **kwargs: Any) -> _NumberedCanvas:
        c = _NumberedCanvas(*args, **kwargs)
        c.footer_left = footer_left
        c.footer_lines = footer_lines
        c.watermark = watermark
        return c

    doc.build(story, canvasmaker=canvasmaker)
    return buf.getvalue()
