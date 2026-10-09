"""Weekly email digest of findings (opt-in) and the nightly backup, on one light scheduler."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from locuvi import db, mail
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.money import fmt_gbp
from locuvi.secrets_store import SecretBox
from locuvi.services import checks, core

log = logging.getLogger("locuvi.digest")

# Plain-English lines for the email (the web UI has its own i18n catalogue).
TEXT: dict[str, str] = {
    "uninvoiced_month": "{month_label} at {practice} is ready to invoice ({n} sessions, {total}).",
    "uninvoiced_current": "{n} worked session(s) at {practice} this month, not invoiced yet.",
    "draft_stale": "A draft invoice for {practice} has not been touched for {days} days.",
    "po_missing": "The draft for {practice} needs a purchase order number.",
    "invoice_overdue": "{number} ({practice}) is {days} days overdue: {outstanding} outstanding.",
    "invoice_due_soon": "{number} ({practice}) is due in {days} day(s): {outstanding}.",
    "invoice_awaiting": "{number} ({practice}) awaiting payment: {outstanding}.",
    "session_duplicate": "Possible duplicate session at {practice} on {date}.",
    "session_overlap": "Overlapping sessions on {date}: {a} and {b}.",
    "pension_due": "{month_label} pension figures are ready (pensionable pay {pay}).",
    "pension_changed": "{month_label} pension figures changed after you marked them submitted.",
    "pension_tier_missing": "Set your employee pension tier to complete Form B figures.",
    "practice_no_address": "{practice} has no billing address.",
    "archive_failed": "Nextcloud upload of {number} failed.",
    "archive_conflict": "Nextcloud already has a different file for {number}.",
    "backup_never": "No backup has been made yet.",
    "backup_stale": "The last backup was {days} days ago.",
    "proposals_pending": "{n} suggested diary change(s) are waiting for you in the inbox.",
    "inbox_waiting": "{n} document(s) have been in your inbox for a few days.",
    "mailbox_failed": "Checking your email folders failed — open Settings › Email folders.",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]  # fmt: skip


def _fmt(f: checks.Finding) -> str:
    p: dict[str, Any] = dict(f.params)
    if "month" in p:
        y, m = (int(x) for x in str(p["month"]).split("-"))
        p["month_label"] = f"{MONTHS[m - 1]} {y}"
    for k in ("total", "outstanding", "pay"):
        if p.get(k) not in (None, ""):
            from decimal import Decimal

            p[k] = fmt_gbp(Decimal(str(p[k])))
    try:
        return TEXT.get(f.kind, f.kind).format(**p)
    except (KeyError, IndexError):
        return f.kind


def compose(s: Session, settings: Settings) -> tuple[str, str] | None:
    findings = [f for f in checks.run_checks(s, settings) if f.kind != "invoice_awaiting"]
    if not findings:
        return None
    counts = checks.summary_counts(findings)
    subject = f"Locuvi: {len(findings)} thing(s) need attention"
    if counts["urgent"]:
        subject += f" ({counts['urgent']} urgent)"
    lines = ["Good morning,", "", "Here is your weekly Locuvi summary:", ""]
    for sev, title in (("urgent", "Urgent"), ("warn", "To do"), ("info", "For information")):
        items = [f for f in findings if f.severity == sev]
        if items:
            lines.append(f"{title}:")
            lines += [f"  • {_fmt(f)}" for f in items]
            lines.append("")
    lines += ["Open Locuvi to act on these. Nothing has been sent or changed automatically.", ""]
    return subject, "\n".join(lines)


def send_now(s: Session, settings: Settings, box: SecretBox, smtp_factory: Any = None) -> dict:
    composed = compose(s, settings)
    if composed is None:
        return {"sent": False, "reason": "nothing_to_report"}
    subject, body = composed
    to = mail.send_to_self(s, settings, box, subject, body, smtp_factory)
    profile = core.get_profile(s)
    profile.last_digest_sent_at = datetime.now(UTC)
    s.commit()
    return {"sent": True, "to": to}


def due(s: Session, now: datetime | None = None) -> bool:
    profile = core.get_profile(s)
    if not profile.digest_enabled or not mail.get_config(s).enabled:
        return False
    local = (now or datetime.now(UTC)).astimezone(core.LONDON)
    if local.weekday() != 0 or local.hour < 8:
        return False
    last = profile.last_digest_sent_at
    if last is None:
        return True
    return last.astimezone(core.LONDON).isocalendar()[:2] != local.isocalendar()[:2]


class DigestScheduler:
    """Checks hourly whether this week's digest is due. Failures are logged, never raised."""

    def __init__(self, settings: Settings, box: SecretBox, interval: float = 3600) -> None:
        self.settings, self.box, self.interval = settings, box, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="digest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        # Wait a minute after start-up, then check hourly.
        while not self._stop.wait(timeout=60):
            self.tick()
            if self._stop.wait(timeout=self.interval - 60):
                return

    def tick(self) -> None:
        from locuvi.services import backups

        try:
            if backups.nightly_due(self.settings):
                backups.backup_now(self.settings)
        except DomainError as exc:
            log.warning("nightly backup not made: %s", exc.code)
        except Exception:  # noqa: BLE001
            log.exception("nightly backup failed")
        try:
            from locuvi.services import documents

            with db.new_session() as s:
                documents.purge_trash(s, self.settings)
        except Exception:  # noqa: BLE001
            log.exception("document trash purge failed")
        try:
            from locuvi.assistant import providers
            from locuvi.services import mailbox

            with db.new_session() as s:
                if mailbox.auto_scan_due(mailbox.get_config(s)):
                    provider = providers.provider_for(s, self.settings, self.box)
                    mailbox.scan(s, self.settings, self.box, provider=provider)
        except DomainError as exc:
            log.warning("mail folder scan not made: %s", exc.code)
        except Exception:  # noqa: BLE001
            log.exception("mail folder scan failed")
        try:
            with db.new_session() as s:
                if due(s):
                    send_now(s, self.settings, self.box)
                    log.info("weekly digest sent")
        except DomainError as exc:
            log.warning("weekly digest not sent: %s", exc.code)
        except Exception:  # noqa: BLE001 — keep the scheduler alive
            log.exception("weekly digest failed")
