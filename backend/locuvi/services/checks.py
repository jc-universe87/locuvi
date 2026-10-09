"""Checks engine: deterministic rules that turn records into *findings*.

A finding says what needs attention, how urgent it is, which record it concerns and what to
do about it. Findings are recomputed on demand (cheap for one user); nothing here changes data.
This is the monitoring layer of docs/specs/AI_AND_AGENTS.md §E — the future assistant reads
these findings rather than guessing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from locuvi.config import Settings
from locuvi.models import (
    ArchiveJob,
    ArchiveStatus,
    BankTransaction,
    CreditNote,
    Document,
    FindingDismissal,
    FormARecord,
    Invoice,
    InvoiceStatus,
    MailboxConfig,
    PcseRecord,
    Practice,
    Proposal,
    SessionStatus,
    WorkSession,
)
from locuvi.services import core, diary, payments, pension

SEVERITY_ORDER = {"urgent": 0, "warn": 1, "info": 2}
OVERLAP_UNITS = {"am": {"am", "day"}, "pm": {"pm", "day"}, "day": {"am", "pm", "day", "hours"}}
BACKUP_MARKER = ".last_backup"


@dataclass
class Finding:
    key: str  # stable identity, used for dismissal
    kind: str  # i18n: finding.<kind>
    severity: str  # urgent | warn | info
    params: dict[str, Any] = field(default_factory=dict)
    ref: dict[str, Any] | None = None  # {"type": "invoice", "id": ...}
    action: dict[str, Any] | None = None  # {"type": "...", ...} — what the UI offers
    dismissible: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def run_checks(s: Session, settings: Settings | None = None, *, today: date | None = None,
               include_dismissed: bool = False) -> list[Finding]:  # fmt: skip
    today = today or core.today_london()
    out: list[Finding] = []
    out += _uninvoiced(s, today)
    out += _drafts(s, today)
    out += _payments(s, today)
    out += _sessions(s, today)
    out += _pension(s, today)
    out += _practices(s)
    out += _archive(s)
    out += _inbox(s, today)
    if settings is not None:
        out += _backup(s, settings, today)
    if not include_dismissed:
        hidden = {
            d.key
            for d in s.scalars(select(FindingDismissal).where(FindingDismissal.until >= today))
        }
        out = [f for f in out if not (f.dismissible and f.key in hidden)]
    out.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.kind, f.key))
    return out


# ------------------------------------------------------------------------- rules


def _uninvoiced(s: Session, today: date) -> list[Finding]:
    out = []
    for g in diary.ready_to_invoice(s):
        month = str(g["month"])
        ended = month < _month(today)
        out.append(Finding(
            key=f"uninvoiced:{g['practice_id']}:{month}",
            kind="uninvoiced_month" if ended else "uninvoiced_current",
            severity="warn" if ended else "info",
            params={"practice": g["practice_name"], "month": month, "n": g["sessions"],
                    "total": g["total"]},
            ref={"type": "practice", "id": g["practice_id"]},
            action={"type": "create_invoice", "practice_id": g["practice_id"], "month": month},
            dismissible=not ended,
        ))  # fmt: skip
    return out


def _drafts(s: Session, today: date) -> list[Finding]:
    out = []
    for d in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.draft)):
        age = (today - d.updated_at.astimezone(core.LONDON).date()).days
        if age >= 7:
            out.append(Finding(
                key=f"draft_stale:{d.id}", kind="draft_stale", severity="info",
                params={"practice": d.practice.name if d.practice else "", "days": age},
                ref={"type": "invoice", "id": d.id},
                action={"type": "open_draft", "invoice_id": d.id},
            ))  # fmt: skip
        if d.practice is not None and d.practice.po_required and not d.reference:
            out.append(Finding(
                key=f"po_missing:{d.id}", kind="po_missing", severity="warn",
                params={"practice": d.practice.name},
                ref={"type": "invoice", "id": d.id},
                action={"type": "open_draft", "invoice_id": d.id}, dismissible=False,
            ))  # fmt: skip
    return out


def _payments(s: Session, today: date) -> list[Finding]:
    out = []
    for inv in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued)):
        st = payments.payment_state(inv, today)
        name = (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", "")
        base = {"number": inv.invoice_number, "practice": name, "outstanding": st["outstanding"]}
        act = {"type": "mark_paid", "invoice_id": inv.id, "number": inv.invoice_number}
        if st["state"] == "refund_due":
            out.append(Finding(
                key=f"refund:{inv.id}", kind="refund_due", severity="warn",
                params={**base, "refund": st["refund_due"]},
                ref={"type": "invoice", "id": inv.id},
                action={"type": "open_invoice", "invoice_id": inv.id}, dismissible=False,
            ))  # fmt: skip
            continue
        if st["state"] == "overdue":
            days = st["days_overdue"]
            out.append(Finding(
                key=f"overdue:{inv.id}", kind="invoice_overdue",
                severity="urgent" if days > 14 else "warn",
                params={**base, "days": days}, ref={"type": "invoice", "id": inv.id},
                action=act, dismissible=False,
            ))  # fmt: skip
        elif st["state"] in {"unpaid", "part_paid"} and inv.due_date:
            left = (inv.due_date - today).days
            out.append(Finding(
                key=f"due:{inv.id}", kind="invoice_due_soon" if left <= 3 else "invoice_awaiting",
                severity="info", params={**base, "days": left, "due": inv.due_date.isoformat()},
                ref={"type": "invoice", "id": inv.id}, action=act,
            ))  # fmt: skip
    return out


def _sessions(s: Session, today: date) -> list[Finding]:
    out = []
    start = today - timedelta(days=120)
    rows = s.scalars(
        select(WorkSession).where(WorkSession.status == SessionStatus.active,
                                  WorkSession.date >= start)
    )  # fmt: skip
    by_day: dict[date, list[WorkSession]] = defaultdict(list)
    for w in rows:
        by_day[w.date].append(w)
    for day, items in sorted(by_day.items()):
        seen: dict[tuple[str, str], WorkSession] = {}
        for w in items:
            k = (w.practice_id, w.unit)
            if k in seen and w.unit != "hours":
                out.append(Finding(
                    key=f"dup:{day}:{w.practice_id}:{w.unit}", kind="session_duplicate",
                    severity="warn",
                    params={"practice": w.practice.name, "date": day.isoformat(), "unit": w.unit},
                    ref={"type": "session", "id": w.id},
                    action={"type": "open_diary", "date": day.isoformat()},
                ))  # fmt: skip
            seen[k] = w
        practices = {w.practice_id for w in items}
        if len(practices) > 1:
            clash = [
                (a, b) for i, a in enumerate(items) for b in items[i + 1:]
                if a.practice_id != b.practice_id and b.unit in OVERLAP_UNITS.get(a.unit, set())
            ]  # fmt: skip
            if clash:
                a, b = clash[0]
                out.append(Finding(
                    key=f"overlap:{day}", kind="session_overlap", severity="warn",
                    params={"date": day.isoformat(), "a": a.practice.name, "b": b.practice.name},
                    ref={"type": "session", "id": a.id},
                    action={"type": "open_diary", "date": day.isoformat()},
                ))  # fmt: skip
    return out


def _pension(s: Session, today: date) -> list[Finding]:
    out = []
    months = pension.overview(s)
    profile = core.get_profile(s)
    submitted = {m["month"] for m in months if m["submitted_on"]}
    for m in months:
        if m["changed_since_submitted"]:
            out.append(Finding(
                key=f"pension_changed:{m['month']}", kind="pension_changed", severity="urgent",
                params={"month": m["month"]}, ref={"type": "pension_month", "id": m["month"]},
                action={"type": "open_pension", "month": m["month"]}, dismissible=False,
            ))  # fmt: skip
        elif m["ready"] and not m["submitted_on"]:
            due = date.fromisoformat(m["due_by"])
            out.append(Finding(
                key=f"pension_due:{m['month']}",
                kind="pension_due" if today <= due else "pension_overdue",
                severity="warn" if (due - today).days > 3 else "urgent",
                params={"month": m["month"], "pay": m["pensionable_pay"],
                        "due": m["due_by"], "days": (due - today).days},
                ref={"type": "pension_month", "id": m["month"]},
                action={"type": "open_pension", "month": m["month"]}, dismissible=False,
            ))  # fmt: skip
    out += _ten_week(s, today, submitted)
    for rec in s.scalars(select(FormARecord).where(FormARecord.status == "sent")):
        if rec.sent_on and (today - rec.sent_on).days > 14:
            inv = s.get(Invoice, rec.practice_key)
            p = s.get(Practice, rec.practice_key)
            name = (
                (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name")
                if inv is not None
                else (p.name if p else rec.practice_key)
            )
            out.append(Finding(
                key=f"form_a_chase:{rec.month}:{rec.practice_key}", kind="form_a_chase",
                severity="warn",
                params={"month": rec.month, "practice": name, "days": (today - rec.sent_on).days},
                ref={"type": "pension_month", "id": rec.month},
                action={"type": "open_pension", "month": rec.month},
            ))  # fmt: skip
    for rec in s.scalars(select(PcseRecord)):
        fig = pension.month_figures(s, rec.month)
        if fig["form_b"]["items"] and fig["pcse"]["status"] == "mismatch":
            out.append(Finding(
                key=f"pcse_mismatch:{rec.month}", kind="pcse_mismatch", severity="warn",
                params={"month": rec.month, "difference": fig["pcse"]["difference"]},
                ref={"type": "pension_month", "id": rec.month},
                action={"type": "open_pension", "month": rec.month},
            ))  # fmt: skip
    if months and profile.employee_rate is None:
        out.append(Finding(
            key="pension_tier_missing", kind="pension_tier_missing", severity="info",
            action={"type": "open_settings", "section": "pension"},
        ))  # fmt: skip
    return out


TEN_WEEK_WARN_DAYS = 28  # start reminding four weeks before the 10-week limit
TEN_WEEK_FORGET_DAYS = 60  # stop after the limit has long passed (nothing left to do)


def _ten_week(s: Session, today: date, submitted: set[str]) -> list[Finding]:
    """Per engagement: pension forms must be in within 10 weeks of the end of the work.

    Covers work not yet invoiced, invoices not yet paid, Form A not yet signed and fees received
    but not yet on a submitted Form B. The 7th-of-month Form B deadline is checked separately.
    """
    out = []

    def add(key: str, stage: str, practice: str, work_end: date, ref: dict[str, Any] | None,
            action: dict[str, Any]) -> None:  # fmt: skip
        deadline = work_end + timedelta(days=pension.TEN_WEEKS)
        left = (deadline - today).days
        if left > TEN_WEEK_WARN_DAYS or left < -TEN_WEEK_FORGET_DAYS:
            return
        out.append(Finding(
            key=f"tenweek:{key}", kind="pension_deadline_passed" if left < 0
            else f"pension_deadline_{stage}",
            severity="urgent" if left <= 7 else "warn",
            params={"practice": practice, "work_end": work_end.isoformat(),
                    "deadline": deadline.isoformat(), "days": left},
            ref=ref, action=action, dismissible=False,
        ))  # fmt: skip

    for inv in pension._pension_invoices(s):
        rec_months = {r["received_month"] for r in pension.receipts(inv)}
        done = payments.outstanding(inv) == 0 and rec_months and rec_months <= submitted
        if done or pension.net_figures(inv)["pay"] <= 0:
            continue
        rec = s.scalars(select(FormARecord).where(FormARecord.practice_key == inv.id)).first()
        if payments.outstanding(inv) > 0:
            stage = "unpaid"
        elif rec is None or rec.status != "signed":
            stage = "form_a"
        else:
            stage = "form_b"
        name = (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", "")
        add(inv.id, stage, name, pension.last_session(inv), {"type": "invoice", "id": inv.id},
            {"type": "open_invoice", "invoice_id": inv.id})  # fmt: skip

    groups: dict[tuple[str, str], list[WorkSession]] = defaultdict(list)
    for w in s.scalars(
        select(WorkSession).where(
            WorkSession.status == SessionStatus.active,
            WorkSession.pensionable.is_(True),
            WorkSession.date <= today,
            WorkSession.date >= today - timedelta(days=pension.TEN_WEEKS + TEN_WEEK_FORGET_DAYS),
        )
    ):
        inv = s.get(Invoice, w.invoice_id) if w.invoice_id else None
        if inv is None or inv.status == InvoiceStatus.draft:
            groups[(w.practice_id, _month(w.date))].append(w)
    for (pid, month), items in groups.items():
        end = max(w.date for w in items)
        add(f"{pid}:{month}", "not_invoiced", items[0].practice.name, end,
            {"type": "practice", "id": pid},
            {"type": "create_invoice", "practice_id": pid, "month": month})  # fmt: skip
    return out


def _practices(s: Session) -> list[Finding]:
    out = []
    used = {pid for pid in s.scalars(select(WorkSession.practice_id).distinct())}
    for p in s.scalars(select(Practice).where(Practice.is_archived.is_(False))):
        if p.id in used and not p.billing_address.strip():
            out.append(Finding(
                key=f"practice_address:{p.id}", kind="practice_no_address", severity="warn",
                params={"practice": p.name}, ref={"type": "practice", "id": p.id},
                action={"type": "open_settings", "section": "practices"}, dismissible=False,
            ))  # fmt: skip
    return out


def _archive(s: Session) -> list[Finding]:
    cfg = core.get_storage_config(s)
    if not cfg.enabled:
        return []
    out = []
    for job in s.scalars(
        select(ArchiveJob).where(ArchiveJob.is_current.is_(True),
                                 ArchiveJob.status.in_([ArchiveStatus.failed,
                                                        ArchiveStatus.conflict]))
    ):  # fmt: skip
        inv = s.get(Invoice, job.invoice_id)
        cn = s.get(CreditNote, job.credit_note_id) if job.credit_note_id else None
        number = cn.number if cn else (inv.invoice_number if inv else "")
        out.append(Finding(
            key=f"archive:{job.id}:{job.status}", kind=f"archive_{job.status}", severity="warn",
            params={"number": number, "error": job.last_error_class},
            ref={"type": "invoice", "id": job.invoice_id},
            action={"type": "open_invoice", "invoice_id": job.invoice_id},
        ))  # fmt: skip
    return out


def _inbox(s: Session, today: date) -> list[Finding]:
    out = []
    waiting = s.scalar(select(func.count(Proposal.id)).where(Proposal.status == "pending"))
    if waiting:
        out.append(Finding(
            key="proposals_pending", kind="proposals_pending", severity="info",
            params={"n": waiting}, action={"type": "open_inbox"}, dismissible=False,
        ))  # fmt: skip
    cutoff = datetime.combine(today - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
    old = s.scalar(
        select(func.count(Document.id)).where(
            Document.status == "new", Document.deleted_at.is_(None), Document.created_at < cutoff
        )
    )
    bank_waiting = s.scalar(
        select(func.count(BankTransaction.id)).where(
            BankTransaction.status.in_(["suggested", "unmatched"])
        )
    )
    if bank_waiting:
        out.append(Finding(
            key="bank_unmatched", kind="bank_unmatched", severity="info",
            params={"n": bank_waiting}, action={"type": "open_bank"}, dismissible=False,
        ))  # fmt: skip
    failing = s.scalars(
        select(MailboxConfig).where(
            MailboxConfig.deleted_at.is_(None),
            MailboxConfig.enabled.is_(True),
            MailboxConfig.last_error.is_not(None),
        )
    )
    for mbox in failing:
        out.append(Finding(
            key=f"mailbox_failed:{mbox.id}", kind="mailbox_failed", severity="warn",
            params={"error": mbox.last_error, "account": mbox.label or mbox.username},
            action={"type": "open_settings", "section": "mailbox"}, dismissible=False,
        ))  # fmt: skip
    if old:
        out.append(Finding(
            key="inbox_waiting", kind="inbox_waiting", severity="info",
            params={"n": old}, action={"type": "open_inbox"},
        ))  # fmt: skip
    return out


def _backup(s: Session, settings: Settings, today: date) -> list[Finding]:
    has_issued = s.scalars(select(Invoice.id).where(Invoice.status != "draft").limit(1)).first()
    if not has_issued:
        return []
    last = last_backup_at(settings)
    act = {"type": "backup_now"} if settings.backup_dir else None
    if last is None:
        return [Finding(key="backup_never", kind="backup_never", severity="warn", action=act)]
    days = (today - last.astimezone(core.LONDON).date()).days
    out = []
    if days > 8:
        out.append(Finding(key=f"backup_stale:{today.isoformat()}", kind="backup_stale",
                           severity="warn", params={"days": days}, action=act))  # fmt: skip
    from locuvi.services import backups

    drill = backups.read_marker(settings, backups.DRILL_MARKER)
    if drill and not drill.get("ok"):
        out.append(Finding(key=f"restore_drill_failed:{drill.get('at')}",
                           kind="restore_drill_failed", severity="urgent",
                           params={"file": drill.get("file", ""), "error": drill.get("error", "")},
                           action=act, dismissible=False))  # fmt: skip
    offsite = backups.read_marker(settings, backups.OFFSITE_MARKER) or {}
    if offsite.get("status") == "failed":
        out.append(Finding(key=f"backup_offsite_failed:{offsite.get('at')}",
                           kind="backup_offsite_failed", severity="warn",
                           params={"error": offsite.get("error", "")}, action=act))  # fmt: skip
    elif not settings.backup_passphrase or offsite.get("status") == "local_only":
        out.append(Finding(key="backup_offsite_off", kind="backup_offsite_off",
                           severity="info"))  # fmt: skip
    return out


# ------------------------------------------------------------------ helpers


def last_backup_at(settings: Settings) -> datetime | None:
    marker = Path(settings.data_dir) / BACKUP_MARKER
    try:
        return datetime.fromisoformat(marker.read_text().strip())
    except (OSError, ValueError):
        return None


def record_backup(settings: Settings) -> None:
    marker = Path(settings.data_dir) / BACKUP_MARKER
    marker.write_text(datetime.now(UTC).isoformat())


def dismiss(s: Session, key: str, days: int = 7) -> None:
    until = core.today_london() + timedelta(days=max(1, min(days, 365)))
    existing = s.get(FindingDismissal, key)
    if existing:
        existing.until = until
    else:
        s.add(FindingDismissal(key=key, until=until))
    s.commit()


def summary_counts(findings: list[Finding]) -> dict[str, int]:
    c = {"urgent": 0, "warn": 0, "info": 0}
    for f in findings:
        c[f.severity] += 1
    return c
