"""Read a booking without AI: dates, AM/PM/day, times and £ rates from plain text.

Handles the common shapes of practice booking emails ("Mon 12th October AM", "12/10/2026
09:00-13:00 £600", "Cancelled: Tuesday 13 Oct PM"). Anything it cannot place becomes a
question rather than a guess. The AI engine, when enabled, returns the same shape.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_NUM = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2}|\d{4})\b")
_DM = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+({_MON})\.?(?:,?\s+(20\d\d))?\b", re.I
)
_MD = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b", re.I)
_TIMES = re.compile(
    r"\b(\d{1,2})(?:[:.](\d\d))?\s*(am|pm)?\s*(?:-|–|to|until)\s*(\d{1,2})(?:[:.](\d\d))?\s*(am|pm)?\b",
    re.I,
)
_MONEY = re.compile(r"£\s?(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?")
# "AM"/"PM" in capitals, after a time ("9am", "2 pm") or as "am session"; plain lower-case
# "am" is ordinary English ("I am pleased to confirm…") and is not taken as a session.
_AM = re.compile(
    r"\bAM\b|\b\d{1,2}(?:[:.]\d\d)?\s?(?:am|a\.m\.)(?![a-z])|(?i:\bam session|\bmorning)"
)
_PM = re.compile(
    r"\bPM\b|\b\d{1,2}(?:[:.]\d\d)?\s?(?:pm|p\.m\.)(?![a-z])"
    r"|(?i:\bpm session|\bafternoon|\bevening)"
)
_DAY = re.compile(
    r"\b(full[- ]day|all[- ]day|whole day|day session|am\s*(?:&|and|\+|/)\s*pm)\b", re.I
)
_CANCEL = re.compile(r"\b(cancel(?:led|ed|lation)?|no longer (?:needed|required))\b", re.I)
_HOURLY = re.compile(r"(per|an|/)\s*(hour|hr)\b", re.I)


def _year_for(month: int, day: int, today: date) -> date | None:
    """Pick the year that puts the date nearest to today (bookings are rarely > 6 months off)."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def _mk(y: int | None, m: int, d: int, today: date) -> date | None:
    if y is None:
        return _year_for(m, d, today)
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(line: str, today: date) -> list[tuple[int, date]]:
    """(position, date) for every date mentioned in a line, UK day-first."""
    out: list[tuple[int, date]] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match[str], d: date | None) -> None:
        if d is None or any(a <= m.start() < b for a, b in taken):
            return
        taken.append((m.start(), m.end()))
        out.append((m.start(), d))

    for m in _ISO.finditer(line):
        add(m, _mk(int(m[1]), int(m[2]), int(m[3]), today))
    for m in _NUM.finditer(line):
        add(m, _mk(int(m[3]), int(m[2]), int(m[1]), today))
    for m in _DM.finditer(line):
        add(m, _mk(int(m[3]) if m[3] else None, MONTHS[m[2].lower()], int(m[1]), today))
    for m in _MD.finditer(line):
        add(m, _mk(int(m[3]) if m[3] else None, MONTHS[m[1].lower()], int(m[2]), today))
    return sorted(out)


def _money(text: str) -> Decimal | None:
    m = _MONEY.search(text)
    if not m:
        return None
    try:
        return Decimal(m[1].replace(",", "") + "." + (m[2] or "00").ljust(2, "0"))
    except InvalidOperation:
        return None


def _minutes(h: str, mins: str | None, ampm: str | None) -> int:
    value = int(h) % 24
    if ampm and ampm.lower() == "pm" and value < 12:
        value += 12
    elif ampm and ampm.lower() == "am" and value == 12:
        value = 0
    elif not ampm and 1 <= value <= 7:
        value += 12  # surgeries don't start at 2am: a bare "2" is 2pm
    return value * 60 + (int(mins) if mins else 0)


def _unit_from(seg: str) -> tuple[str | None, Decimal | None]:
    """Session type from words, else from a time range. Returns (unit, hours)."""
    if _DAY.search(seg):
        return "day", None
    am, pm = bool(_AM.search(seg)), bool(_PM.search(seg))
    t = _TIMES.search(seg)
    if t:
        start = _minutes(t[1], t[2], t[3])
        end = _minutes(t[4], t[5], t[6] or t[3])
        if not t[3] and t[6] and t[6].lower() == "pm" and end - start >= 12 * 60:
            start += 12 * 60  # "2-6pm": the pm applies to both ends
        if end <= start and end < 12 * 60:
            end += 12 * 60  # "2-6" means 14:00-18:00
        length = (Decimal(end - start) / 60).quantize(Decimal("0.01")) if end > start else None
        if start < 12 * 60 and end > 14 * 60:
            return "day", length
        return ("am" if start < 12 * 60 else "pm"), length
    if am and pm:
        return "day", None
    if am:
        return "am", None
    if pm:
        return "pm", None
    return None, None


def extract(text: str, today: date) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    questions: list[str] = []
    global_rate = _money(text)
    rates = {_money(m.group(0)) for m in _MONEY.finditer(text)}
    hourly_text = bool(_HOURLY.search(text))
    seen: set[tuple[str, str, str]] = set()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if re.match(r"^\s*(>|from:|sent:|to:|subject:|date:)", line, re.I):
            continue  # quoted replies and headers
        found = find_dates(line, today)
        if not found:
            continue
        cancel = bool(_CANCEL.search(line))
        for i, (pos, d) in enumerate(found):
            end = found[i + 1][0] if i + 1 < len(found) else len(line)
            seg = line[pos:end]
            unit, hours = _unit_from(seg)
            if unit is None and len(found) == 1:
                unit, hours = _unit_from(line)
            rate = _money(seg) or (_money(line) if len(found) == 1 else None)
            if rate is None and len(rates) == 1:
                rate = global_rate
            item = {
                "date": d.isoformat(),
                "unit": unit or "day",
                "hours": None,
                "practice_id": None,
                "practice_name": None,
                "rate": str(rate) if rate is not None else None,
                "action": "cancel" if cancel else "add",
                "note": None if unit else "Session type not stated — assumed a full day.",
            }
            if hourly_text and hours is not None and rate is not None and rate < 200:
                item["unit"], item["hours"] = "hours", str(hours)
            key = (item["date"], item["unit"], item["action"])
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    if not items:
        questions.append("No session dates were found. Which days is this booking for?")
    elif any(i["rate"] is None for i in items) and len(rates) > 1:
        questions.append("Several amounts are mentioned. Check the rate for each session.")
    return {"summary": "", "items": items[:62], "questions": questions}
