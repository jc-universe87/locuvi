"""Email reminders before NHS pension deadlines (opt-in, Settings › NHS pension).

Built on the same checks as Today, so the email and the screen always agree. Each reminder is
sent once per stage: Form B five days before the 7th and again if it's late; the 10-week limit
two weeks before and again if it passes; a Form A waiting more than two weeks for the
practice's signature. At most one email a day, from 8am, and only when something new is due.
Nothing is submitted or changed: the email only says what to do.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from locuvi import mail
from locuvi.config import Settings
from locuvi.secrets_store import SecretBox
from locuvi.services import checks, core

log = logging.getLogger("locuvi.pension_reminders")

FORM_B_DAYS = 5  # remind this many days before the 7th
TEN_WEEK_DAYS = 14  # and this many days before the 10-week limit
KEEP = 300  # remembered reminders (oldest dropped)


def _mark(f: checks.Finding) -> str | None:
    """The once-only mark for a pension finding worth an email now, else None."""
    days = f.params.get("days")
    if f.kind == "pension_due":
        return f"{f.key}:soon" if days is not None and days <= FORM_B_DAYS else None
    if f.kind == "pension_overdue":
        return f"{f.key}:late"
    if f.kind == "pension_deadline_passed":
        return f"{f.key}:passed"
    if f.kind.startswith("pension_deadline_"):  # not invoiced / unpaid / Form A / Form B
        return f"{f.key}:{f.kind}" if days is not None and days <= TEN_WEEK_DAYS else None
    if f.kind == "form_a_chase":
        return f.key
    return None


def due_items(
    s: Session, settings: Settings, today: date | None = None
) -> list[tuple[checks.Finding, str, bool]]:
    """(finding, mark, new) for every pension deadline worth reminding about today."""
    sent = set(core.get_profile(s).pension_reminders_sent or [])
    out = []
    for f in checks.run_checks(s, settings, today=today, include_dismissed=True):
        mark = _mark(f)
        if mark:
            out.append((f, mark, mark not in sent))
    return out


def compose(items: list[tuple[checks.Finding, str, bool]]) -> tuple[str, str]:
    from locuvi.services.digest import _fmt  # the same plain-English lines as the summary

    new = [f for f, _, is_new in items if is_new]
    others = [f for f, _, is_new in items if not is_new]
    subject = "Locuvi: NHS pension deadline" + ("s" if len(new) > 1 else "") + " coming up"
    if any(f.kind in {"pension_overdue", "pension_deadline_passed"} for f in new):
        subject = "Locuvi: an NHS pension deadline has passed"
    lines = ["Good morning,", "", "Reminder about your NHS pension forms:", ""]
    lines += [f"  • {_fmt(f)}" for f in new]
    if others:
        lines += ["", "Still to do from earlier reminders:", ""]
        lines += [f"  • {_fmt(f)}" for f in others]
    lines += [
        "",
        "Send the forms and pay on PCSE Online: "
        "https://pcse.england.nhs.uk/services/gp-pensions/locum-gps",
        "Open Locuvi › Pension for the figures. Then record what you've sent there, so these "
        "reminders stop.",
        "",
        "Locuvi doesn't submit anything to PCSE. Turn these emails off in Settings › NHS pension.",
        "",
    ]
    return subject, "\n".join(lines)


def due(s: Session, now: datetime | None = None) -> bool:
    profile = core.get_profile(s)
    if not profile.pension_reminders or not mail.get_config(s).enabled:
        return False
    return (now or datetime.now(UTC)).astimezone(core.LONDON).hour >= 8


def send_if_due(
    s: Session, settings: Settings, box: SecretBox, smtp_factory: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Send one email if a new reminder is due. Safe to call every hour."""
    now = now or datetime.now(UTC)
    if not due(s, now):
        return {"sent": False, "reason": "off_or_too_early"}
    items = due_items(s, settings, now.astimezone(core.LONDON).date())
    if not any(is_new for _, _, is_new in items):
        return {"sent": False, "reason": "nothing_new"}
    subject, body = compose(items)
    to = mail.send_to_self(s, settings, box, subject, body, smtp_factory)
    profile = core.get_profile(s)
    marks = list(profile.pension_reminders_sent or [])
    marks += [mark for _, mark, is_new in items if is_new]
    profile.pension_reminders_sent = marks[-KEEP:]
    core.audit(s, "pension.reminder_sent", count=sum(1 for *_, n in items if n))
    s.commit()
    return {"sent": True, "to": to, "count": sum(1 for *_, n in items if n)}
