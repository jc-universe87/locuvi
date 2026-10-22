"""Private calendar feed (ICS) of booked sessions, for subscribing on a phone.

The feed URL carries a long random secret; anyone with the link can read the events, so it is
shown only to the owner, can be regenerated (old link stops working) and turned off. Fees are
left out unless the owner chooses to include them. Times are the usual surgery blocks.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.models import CalendarFeed, SessionStatus, WorkSession
from locuvi.money import fmt_gbp
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import core

TIMES = {"am": ("080000", "130000"), "pm": ("130000", "183000"), "day": ("080000", "183000")}
UNIT_LABEL = {"am": "AM", "pm": "PM", "day": "Full day", "hours": "Hours", "custom": "Session"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get(s: Session) -> CalendarFeed:
    feed = s.get(CalendarFeed, 1)
    if feed is None:
        feed = CalendarFeed(id=1)
        s.add(feed)
        s.flush()
    return feed


def public(feed: CalendarFeed, box: SecretBox) -> dict[str, Any]:
    token = None
    if feed.enabled and feed.token_ciphertext:
        try:
            token = box.decrypt(feed.token_ciphertext)
        except SecretUnavailable:
            token = None
    return {
        "enabled": feed.enabled and token is not None,
        "include_fees": feed.include_fees,
        "path": f"/calendar/{token}.ics" if token else None,
    }


def enable(s: Session, box: SecretBox, *, include_fees: bool, regenerate: bool = False) -> None:
    feed = get(s)
    if regenerate or not feed.token_ciphertext:
        token = secrets.token_urlsafe(32)
        feed.token_ciphertext, feed.token_hash = box.encrypt(token), _hash(token)
    feed.enabled, feed.include_fees = True, include_fees
    core.audit(s, "calendar.enabled", include_fees=include_fees, regenerated=regenerate)
    s.commit()


def disable(s: Session) -> None:
    feed = get(s)
    feed.enabled = False
    feed.token_ciphertext = feed.token_hash = None
    core.audit(s, "calendar.disabled")
    s.commit()


def lookup(s: Session, token: str) -> CalendarFeed | None:
    feed = s.get(CalendarFeed, 1)
    if feed is None or not feed.enabled or not feed.token_hash:
        return None
    return feed if hmac.compare_digest(feed.token_hash, _hash(token)) else None


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets are folded with CRLF + space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _sessions(s: Session, start: date | None, end: date | None) -> list[WorkSession]:
    stmt = select(WorkSession)
    if start:
        stmt = stmt.where(WorkSession.date >= start)
    if end:
        stmt = stmt.where(WorkSession.date <= end)
    return list(s.scalars(stmt.order_by(WorkSession.date)))


def _label(w: WorkSession) -> str:
    if w.unit == "hours":
        return f"{w.quantity.normalize():f} h"
    return UNIT_LABEL.get(w.unit, "Session")


def render(
    s: Session, feed: CalendarFeed | None = None, today: date | None = None, *,
    include_fees: bool | None = None, everything: bool = False,
) -> str:  # fmt: skip
    """The subscription feed (a window around today), or with ``everything`` a one-off export
    of all sessions. Fees only if the feed or ``include_fees`` says so."""
    today = today or core.today_london()
    fees = include_fees if include_fees is not None else bool(feed and feed.include_fees)
    if everything:
        rows = _sessions(s, None, None)
    else:
        rows = _sessions(s, today - timedelta(days=90), today + timedelta(days=550))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Locuvi//Sessions//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Locum sessions",
             "X-PUBLISHED-TTL:PT1H", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]  # fmt: skip
    for w in rows:
        d = w.date.strftime("%Y%m%d")
        summary = f"Locum {_label(w)} · {w.practice.name}"
        ev = ["BEGIN:VEVENT", f"UID:{w.id}@locuvi", f"DTSTAMP:{stamp}",
              f"SUMMARY:{_esc(summary)}"]  # fmt: skip
        if w.unit in TIMES:
            a, b = TIMES[w.unit]
            ev += [f"DTSTART:{d}T{a}", f"DTEND:{d}T{b}"]  # local (floating) times
        else:
            nxt = (w.date + timedelta(days=1)).strftime("%Y%m%d")
            ev += [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}"]
        if w.practice.billing_address:
            ev.append(f"LOCATION:{_esc(w.practice.billing_address.replace(chr(10), ', '))}")
        if fees:
            ev.append(f"DESCRIPTION:{_esc(fmt_gbp(w.rate * w.quantity))}")
        ev.append("STATUS:CANCELLED" if w.status == SessionStatus.cancelled else "STATUS:CONFIRMED")
        ev.append("TRANSP:OPAQUE")
        ev.append("END:VEVENT")
        lines += ev
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def render_csv(s: Session, *, include_fees: bool) -> str:
    """All sessions as a spreadsheet: ISO dates and 24-hour times, one row per session."""
    import csv
    import io

    out = io.StringIO()
    w = csv.writer(out)
    head = ["Date", "Start", "End", "Session", "Practice", "Address", "Status"]
    w.writerow(head + (["Fee"] if include_fees else []))
    for row in _sessions(s, None, None):
        a, b = TIMES.get(row.unit, ("", ""))
        start, end = (f"{a[:2]}:{a[2:4]}", f"{b[:2]}:{b[2:4]}") if a else ("", "")
        address = (row.practice.billing_address or "").replace("\n", ", ")
        status = "Cancelled" if row.status == SessionStatus.cancelled else "Booked"
        cells = [row.date.isoformat(), start, end, _label(row), row.practice.name, address, status]
        if include_fees:
            cells.append(f"{(row.rate * row.quantity).quantize(Decimal('0.01'))}")
        # a cell starting with = + - @ would run as a formula in a spreadsheet
        w.writerow(["'" + c if c[:1] in "=+-@" else c for c in cells])
    return out.getvalue()
