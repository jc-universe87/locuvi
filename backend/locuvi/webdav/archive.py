"""One-way archive of issued invoice PDFs to Nextcloud / generic WebDAV.

The local database and local PDF stay authoritative; archive state never
affects whether an invoice is issued.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import (
    ArchiveJob,
    ArchiveStatus,
    CreditNote,
    Invoice,
    InvoiceEvent,
    StorageConfig,
)
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import core
from locuvi.storage.local import resolve, sha256_bytes
from locuvi.webdav.client import MAX_DOWNLOAD, PAUSING_ERRORS, WebDavClient, WebDavError
from locuvi.webdav.urlguard import (
    InvalidPath,
    UrlBlocked,
    ValidatedUrl,
    encode_path,
    validate_base_path,
    validate_base_url,
    validate_segment,
)

log = logging.getLogger("locuvi.archive")

BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 6 * 3600
MAX_AUTO_ATTEMPTS = 10

TransportFactory = Callable[[], httpx.BaseTransport | None]


@dataclass
class ArchiveContext:
    settings: Settings
    secrets: SecretBox
    transport_factory: TransportFactory = lambda: None  # noqa: E731 (tests inject fakes)
    check_dns: bool = True


# ------------------------------------------------------------------ configuration


def password_source(ctx: ArchiveContext, cfg: StorageConfig) -> str:
    if ctx.settings.webdav_password_override:
        return "secret_file"
    return "stored" if cfg.password_ciphertext else "none"


def get_password(ctx: ArchiveContext, cfg: StorageConfig) -> str:
    if ctx.settings.webdav_password_override:
        return ctx.settings.webdav_password_override
    if not cfg.password_ciphertext:
        raise WebDavError("credentials_unavailable", "no app password saved")
    try:
        return ctx.secrets.decrypt(cfg.password_ciphertext)
    except SecretUnavailable:
        raise WebDavError("credentials_unavailable", "saved app password unreadable") from None


def config_public(ctx: ArchiveContext, cfg: StorageConfig) -> dict[str, Any]:
    """Safe view of the config: never includes the secret."""
    return {
        "enabled": cfg.enabled,
        "target_url": cfg.target_url,
        "username": cfg.username,
        "base_path": cfg.base_path,
        "auto_upload": cfg.auto_upload,
        "password_set": password_source(ctx, cfg) != "none",
        "password_source": password_source(ctx, cfg),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _validate(
    ctx: ArchiveContext, target_url: str, username: str, base_path: str
) -> tuple[ValidatedUrl, list[str]]:
    try:
        vurl = validate_base_url(target_url, ctx.settings)
    except UrlBlocked as exc:
        raise DomainError("webdav.url_blocked", str(exc), reason=exc.reason) from None
    if not username.strip() or len(username) > 200 or any(ord(c) < 32 for c in username):
        raise DomainError("webdav.username_required", "Enter the Nextcloud username.")
    try:
        segments = validate_base_path(base_path)
    except InvalidPath as exc:
        raise DomainError("webdav.invalid_folder", str(exc)) from None
    return vurl, segments


def save_config(
    s: Session,
    ctx: ArchiveContext,
    *,
    enabled: bool,
    target_url: str,
    username: str,
    base_path: str,
    auto_upload: bool,
    password: str | None,
) -> StorageConfig:
    cfg = core.get_storage_config(s)
    target_url = target_url.strip()
    if enabled or target_url:
        vurl, segments = _validate(ctx, target_url, username, base_path)
        target_url = vurl.url
        base_path = "/".join(segments)
    if password is not None:
        if password == "":
            cfg.password_ciphertext = None
        else:
            if len(password) > 500:
                raise DomainError("webdav.password_invalid", "The app password is too long.")
            cfg.password_ciphertext = ctx.secrets.encrypt(password)
    if enabled and password_source(ctx, cfg) == "none":
        raise DomainError("webdav.password_required", "Enter a Nextcloud app password.")
    destination_changed = (
        cfg.target_url != target_url or cfg.username != username or cfg.base_path != base_path
    )
    cfg.enabled = enabled
    cfg.target_url = target_url
    cfg.username = username.strip()
    cfg.base_path = base_path
    cfg.auto_upload = auto_upload
    cfg.config_version += 1
    core.audit(
        s,
        "storage.webdav_saved",
        enabled=enabled,
        auto_upload=auto_upload,
        destination_changed=destination_changed,
        password_changed=password is not None,
    )
    s.flush()
    _retarget_unsynced_jobs(s, cfg)
    s.commit()
    return cfg


def _retarget_unsynced_jobs(s: Session, cfg: StorageConfig) -> None:
    """After a config change, unsynced jobs move to the new destination and resume.

    Synced jobs keep their history and are not re-uploaded. A conflict stays a conflict at
    the same destination, but moves to the new destination when the owner changes it.
    """
    now = datetime.now(UTC)
    jobs = s.scalars(
        select(ArchiveJob).where(
            ArchiveJob.is_current.is_(True),
            ArchiveJob.status.in_(
                [ArchiveStatus.pending, ArchiveStatus.failed, ArchiveStatus.conflict]
            ),
        )
    ).all()
    for job in jobs:
        inv = s.get(Invoice, job.invoice_id)
        if inv is None or not cfg.enabled:
            continue
        if job.credit_note_id:
            cn = s.get(CreditNote, job.credit_note_id)
            if cn is None:
                continue
            if credit_destination_for(cfg, cn)[0] == job.destination_key:
                if job.status != ArchiveStatus.conflict:
                    job.next_retry_at, job.status = now, ArchiveStatus.pending
                    job.last_error_class, job.attempt_count = None, 0
            else:
                job.is_current = False
                _make_credit_job(s, cfg, cn)
            continue
        dest = destination_for(cfg, inv)
        if dest[0] == job.destination_key:
            if job.status == ArchiveStatus.conflict:
                continue
            job.next_retry_at = now
            job.status = ArchiveStatus.pending
            job.last_error_class = None
            job.attempt_count = 0
        else:
            job.is_current = False
            _make_job(s, cfg, inv)


def destination_for(cfg: StorageConfig, inv: Invoice) -> tuple[str, str]:
    """(destination_key, encoded relative path) — privacy-friendly number-only name."""
    if inv.invoice_number is None or inv.invoice_date is None:
        raise ValueError("invoice is not issued")
    segments = validate_base_path(cfg.base_path) + [
        f"{inv.invoice_date.year:04d}",
        f"{inv.invoice_date.month:02d}",
        validate_segment(f"{inv.invoice_number}.pdf"),
    ]
    rel = encode_path(segments)
    return f"{cfg.target_url}|{cfg.username}|{rel}", rel


def credit_destination_for(cfg: StorageConfig, cn: CreditNote) -> tuple[str, str]:
    """Credit notes sit next to invoices: <base>/YYYY/MM/CN-0001.pdf by credit date."""
    segments = validate_base_path(cfg.base_path) + [
        f"{cn.credit_date.year:04d}",
        f"{cn.credit_date.month:02d}",
        validate_segment(f"{cn.number}.pdf"),
    ]
    rel = encode_path(segments)
    return f"{cfg.target_url}|{cfg.username}|{rel}", rel


def _make_credit_job(s: Session, cfg: StorageConfig, cn: CreditNote) -> ArchiveJob:
    key, rel = credit_destination_for(cfg, cn)
    now = datetime.now(UTC)
    jobs = list(s.scalars(select(ArchiveJob).where(ArchiveJob.credit_note_id == cn.id)))
    for old in jobs:
        if old.is_current and old.destination_key != key:
            old.is_current = False
    job = next((j for j in jobs if j.destination_key == key), None)
    if job is None:
        job = ArchiveJob(
            invoice_id=cn.invoice_id,
            credit_note_id=cn.id,
            destination_key=key,
            destination_url_snapshot=cfg.target_url,
            destination_path_snapshot=rel,
            pdf_sha256=cn.local_pdf_sha256,
            status=ArchiveStatus.pending,
            next_retry_at=now,
        )
        s.add(job)
    else:
        job.is_current = True
        if job.status != ArchiveStatus.synced:
            job.status, job.next_retry_at = ArchiveStatus.pending, now
            job.attempt_count, job.last_error_class = 0, None
    return job


def enqueue_credit_note(s: Session, cn: CreditNote) -> None:
    """Called inside the credit-note issue transaction; never raises for remote problems."""
    cfg = core.get_storage_config(s)
    if not (cfg.enabled and cfg.auto_upload and cfg.target_url):
        return
    try:
        _make_credit_job(s, cfg, cn)
    except (ValueError, InvalidPath):
        log.warning("archive job not created for credit note %s: invalid destination", cn.id)


def credit_archive_status(s: Session, cn: CreditNote) -> str:
    job = s.scalars(
        select(ArchiveJob).where(
            ArchiveJob.credit_note_id == cn.id, ArchiveJob.is_current.is_(True)
        )
    ).first()
    if job is None:
        return ArchiveStatus.not_configured
    return ArchiveStatus.pending if job.status == ArchiveStatus.uploading else job.status


def _make_job(s: Session, cfg: StorageConfig, inv: Invoice) -> ArchiveJob:
    key, rel = destination_for(cfg, inv)
    for old in inv.archive_jobs:
        if old.is_current and old.destination_key != key:
            old.is_current = False
    job = s.scalars(
        select(ArchiveJob).where(ArchiveJob.invoice_id == inv.id, ArchiveJob.destination_key == key)
    ).first()
    now = datetime.now(UTC)
    if job is None:
        job = ArchiveJob(
            invoice_id=inv.id,
            destination_key=key,
            destination_url_snapshot=cfg.target_url,
            destination_path_snapshot=rel,
            pdf_sha256=inv.local_pdf_sha256 or "",
            status=ArchiveStatus.pending,
            next_retry_at=now,
        )
        s.add(job)
        inv.archive_jobs.append(job)
    else:
        job.is_current = True
        if job.status != ArchiveStatus.synced:
            job.status = ArchiveStatus.pending
            job.next_retry_at = now
            job.attempt_count = 0
            job.last_error_class = None
    return job


def enqueue_on_issue(s: Session, inv: Invoice) -> None:
    """Called inside the issue transaction; never raises for remote problems."""
    cfg = core.get_storage_config(s)
    if not (cfg.enabled and cfg.auto_upload and cfg.target_url):
        return
    try:
        _make_job(s, cfg, inv)
    except (ValueError, InvalidPath):
        log.warning("archive job not created for invoice %s: invalid destination", inv.id)


def request_upload(s: Session, inv: Invoice) -> ArchiveJob:
    """Manual 'Retry upload' / 'Upload now' / 're-upload if confirmed missing'."""
    if inv.status == "draft" or not inv.local_pdf_sha256:
        raise DomainError("archive.not_issued", "Only issued invoices can be archived.")
    cfg = core.get_storage_config(s)
    if not cfg.enabled or not cfg.target_url:
        raise DomainError("archive.not_configured", "Nextcloud / WebDAV is not enabled.")
    job = _make_job(s, cfg, inv)
    if job.status == ArchiveStatus.synced or job.status == ArchiveStatus.conflict:
        # Re-verify: the worker re-checks the remote file and uploads it if missing.
        job.status = ArchiveStatus.pending
        job.next_retry_at = datetime.now(UTC)
        job.attempt_count = 0
    s.add(InvoiceEvent(invoice_id=inv.id, event_type="archive_requested", metadata_json={}))
    s.commit()
    return job


def archive_backlog(s: Session) -> dict[str, int]:
    """Issued/voided invoices and credit notes by archive state, for the bulk upload button."""
    counts = {"not_archived": 0, "pending": 0, "synced": 0, "failed": 0, "conflict": 0}
    for inv in s.scalars(select(Invoice).where(Invoice.status != "draft")):
        job = next((j for j in inv.archive_jobs if j.is_current), None)
        state = job.status if job else "not_archived"
        if state == ArchiveStatus.uploading:
            state = "pending"
        counts[state] = counts.get(state, 0) + 1
    for cn in s.scalars(select(CreditNote)):
        state = credit_archive_status(s, cn)
        state = "not_archived" if state == ArchiveStatus.not_configured else state
        counts[state] = counts.get(state, 0) + 1
    return counts


def request_upload_all(s: Session) -> int:
    """Queue every issued/voided invoice that has no archive copy yet (or failed).

    Synced, conflicting and already-queued jobs are left alone; nothing is re-uploaded.
    """
    cfg = core.get_storage_config(s)
    if not cfg.enabled or not cfg.target_url:
        raise DomainError("archive.not_configured", "Nextcloud / WebDAV is not enabled.")
    queued = 0
    for inv in s.scalars(select(Invoice).where(Invoice.status != "draft")):
        if not inv.local_pdf_sha256 or not inv.invoice_number:
            continue
        job = next((j for j in inv.archive_jobs if j.is_current), None)
        if job is not None and job.status != ArchiveStatus.failed:
            continue
        before = job.status if job else None
        job = _make_job(s, cfg, inv)
        if before == ArchiveStatus.failed or job.status == ArchiveStatus.pending:
            queued += 1
    for cn in s.scalars(select(CreditNote)):
        state = credit_archive_status(s, cn)
        if state in (ArchiveStatus.not_configured, ArchiveStatus.failed):
            _make_credit_job(s, cfg, cn)
            queued += 1
    if queued:
        core.audit(s, "storage.archive_all_requested", queued=queued)
    s.commit()
    return queued


def archive_status(s: Session, inv: Invoice) -> dict[str, Any]:
    cfg = core.get_storage_config(s)
    job = next((j for j in reversed(inv.archive_jobs) if j.is_current), None)
    if job is None:
        return {"status": ArchiveStatus.not_configured, "webdav_enabled": cfg.enabled}
    return {
        "status": job.status,
        "webdav_enabled": cfg.enabled,
        "attempt_count": job.attempt_count,
        "last_attempt_at": job.last_attempt_at.isoformat() if job.last_attempt_at else None,
        "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
        "last_error_class": job.last_error_class,
        "remote_path": job.destination_path_snapshot,
        "remote_etag": job.remote_etag,
        "verified_sha256": job.verified_sha256,
        "local_sha256": job.pdf_sha256,
        "retry_paused": job.status == ArchiveStatus.failed and job.next_retry_at is None,
    }


# ---------------------------------------------------------------------- testing


def test_connection(
    s: Session,
    ctx: ArchiveContext,
    *,
    target_url: str | None,
    username: str | None,
    base_path: str | None,
    password: str | None,
) -> dict[str, Any]:
    """Check credentials and folder without persisting anything."""
    cfg = core.get_storage_config(s)
    url = target_url if target_url is not None else cfg.target_url
    user = username if username is not None else cfg.username
    path = base_path if base_path is not None else cfg.base_path
    vurl, segments = _validate(ctx, url, user, path)
    try:
        pw = password if password else get_password(ctx, cfg)
    except WebDavError as exc:
        return {"ok": False, "error_class": exc.error_class}
    try:
        with _client(ctx, vurl, user, pw) as c:
            root = c.stat("")
            if not root.exists or not root.is_collection:
                return {"ok": False, "error_class": "base_not_found"}
            folder = c.stat(encode_path(segments)) if segments else root
            return {"ok": True, "folder_exists": folder.exists and folder.is_collection}
    except WebDavError as exc:
        return {"ok": False, "error_class": exc.error_class}


def _client(ctx: ArchiveContext, vurl: ValidatedUrl, user: str, pw: str) -> WebDavClient:
    return WebDavClient(
        vurl, user, pw, ctx.settings, transport=ctx.transport_factory(), check_dns=ctx.check_dns
    )


# ------------------------------------------------------------------- processing


def upload_verified(
    c: WebDavClient,
    rel: str,
    data: bytes,
    sha: str,
    tag: str,
    content_type: str = "application/pdf",
) -> str | None:
    """Upload idempotently without ever replacing different remote content.

    Returns the remote etag (if reported). Raises WebDavError('conflict') if a
    different file already occupies the target path.
    """
    parts = rel.split("/")
    folder, name = parts[:-1], parts[-1]
    if folder and not c.stat("/".join(folder)).exists:
        for i in range(1, len(folder) + 1):
            c.mkcol("/".join(folder[:i]))

    existing = c.stat(rel)
    if existing.exists:
        return _confirm_same(c, rel, sha, existing.etag, max(len(data), MAX_DOWNLOAD))

    part = "/".join([*folder, f".{name}.locuvi-{tag}.part"])
    c.put(part, data, content_type)
    try:
        moved = c.move_no_overwrite(part, rel)
    except WebDavError:
        c.delete_quietly(part)
        raise
    if not moved:
        c.delete_quietly(part)
        return _confirm_same(c, rel, sha, None, max(len(data), MAX_DOWNLOAD))
    remote_sha = c.get_sha256(rel, max_bytes=max(len(data), MAX_DOWNLOAD))
    if remote_sha != sha:
        raise WebDavError("verify_failed", "remote file does not match after upload")
    return c.stat(rel).etag


def _confirm_same(
    c: WebDavClient, rel: str, sha: str, etag: str | None, max_bytes: int = MAX_DOWNLOAD
) -> str | None:
    remote_sha = c.get_sha256(rel, max_bytes=max_bytes)
    if remote_sha is None:
        raise WebDavError("protocol_error", "remote file vanished during verification")
    if remote_sha != sha:
        raise WebDavError("conflict", "a different file already exists at the target path")
    return etag or c.stat(rel).etag


def backoff_seconds(attempt: int) -> float:
    return float(min(BASE_BACKOFF_SECONDS * 2 ** max(0, attempt - 1), MAX_BACKOFF_SECONDS))


def _claim(job_id: str) -> bool:
    with db.new_session() as s:
        res = s.execute(
            update(ArchiveJob)
            .where(
                ArchiveJob.id == job_id,
                ArchiveJob.is_current.is_(True),
                ArchiveJob.status.in_([ArchiveStatus.pending, ArchiveStatus.failed]),
            )
            .values(
                status=ArchiveStatus.uploading,
                attempt_count=ArchiveJob.attempt_count + 1,
                last_attempt_at=datetime.now(UTC),
            )
        )
        s.commit()
        return res.rowcount == 1


def process_job(ctx: ArchiveContext, job_id: str) -> str:
    """Run one attempt for a job. Returns the resulting status."""
    if not _claim(job_id):
        return "skipped"
    s = db.new_session()
    try:
        job = s.get(ArchiveJob, job_id)
        assert job is not None
        inv = s.get(Invoice, job.invoice_id)
        cfg = core.get_storage_config(s)
        try:
            if not cfg.enabled or job.destination_url_snapshot != cfg.target_url:
                raise WebDavError("not_configured", "WebDAV disabled or destination changed")
            source = s.get(CreditNote, job.credit_note_id) if job.credit_note_id else inv
            if source is None:
                raise WebDavError("local_file_missing", "credit note not found")
            data = resolve(ctx.settings.data_dir, source.local_pdf_path or "").read_bytes()
            if sha256_bytes(data) != job.pdf_sha256:
                raise WebDavError("local_integrity", "local PDF checksum mismatch")
            vurl = validate_base_url(cfg.target_url, ctx.settings)
            pw = get_password(ctx, cfg)
            with _client(ctx, vurl, cfg.username, pw) as c:
                etag = upload_verified(
                    c, job.destination_path_snapshot, data, job.pdf_sha256, job.id[:8]
                )
            job.status = ArchiveStatus.synced
            job.remote_etag = etag
            job.verified_sha256 = job.pdf_sha256
            job.last_error_class = None
            job.next_retry_at = None
            s.add(
                InvoiceEvent(
                    invoice_id=inv.id,
                    event_type="archive_synced",
                    metadata_json={
                        "path": job.destination_path_snapshot,
                        **({"credit_note_id": job.credit_note_id} if job.credit_note_id else {}),
                    },
                )
            )
        except (WebDavError, UrlBlocked, OSError) as exc:
            err = (
                exc.error_class
                if isinstance(exc, WebDavError)
                else "url_blocked"
                if isinstance(exc, UrlBlocked)
                else "local_file_missing"
            )
            _record_failure(s, job, inv, err, getattr(exc, "retry_after", None))
        s.commit()
        log.info(
            "archive job=%s invoice=%s status=%s error=%s",
            job.id,
            inv.id,
            job.status,
            job.last_error_class,
        )
        return job.status
    except BaseException:
        s.rollback()
        # Never leave a job stuck in 'uploading'.
        with db.new_session() as s2:
            s2.execute(
                update(ArchiveJob)
                .where(ArchiveJob.id == job_id, ArchiveJob.status == ArchiveStatus.uploading)
                .values(
                    status=ArchiveStatus.failed,
                    last_error_class="internal_error",
                    next_retry_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            s2.commit()
        raise
    finally:
        s.close()


def _record_failure(
    s: Session, job: ArchiveJob, inv: Invoice | None, err: str, retry_after: float | None
) -> None:
    now = datetime.now(UTC)
    job.last_error_class = err
    if err == "conflict":
        job.status = ArchiveStatus.conflict
        job.next_retry_at = None
    else:
        job.status = ArchiveStatus.failed
        if (
            err in PAUSING_ERRORS
            or err == "local_integrity"
            or job.attempt_count >= MAX_AUTO_ATTEMPTS
        ):
            job.next_retry_at = None  # paused until settings change or manual retry
        else:
            delay = max(backoff_seconds(job.attempt_count), retry_after or 0)
            job.next_retry_at = now + timedelta(seconds=min(delay, MAX_BACKOFF_SECONDS))
    if inv is not None:
        s.add(
            InvoiceEvent(
                invoice_id=inv.id,
                event_type="archive_failed",
                metadata_json={"error_class": err, "attempt": job.attempt_count},
            )
        )


def due_job_ids(s: Session, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    cfg = core.get_storage_config(s)
    if not cfg.enabled:
        return []
    rows = s.scalars(
        select(ArchiveJob.id)
        .where(
            ArchiveJob.is_current.is_(True),
            ArchiveJob.status.in_([ArchiveStatus.pending, ArchiveStatus.failed]),
            ArchiveJob.next_retry_at.is_not(None),
            ArchiveJob.next_retry_at <= now,
        )
        .order_by(ArchiveJob.next_retry_at)
        .limit(20)
    )
    return list(rows)


def recover_interrupted(s: Session) -> int:
    """At startup, jobs left in 'uploading' (crash mid-upload) become pending again."""
    res = s.execute(
        update(ArchiveJob)
        .where(ArchiveJob.status == ArchiveStatus.uploading)
        .values(status=ArchiveStatus.pending, next_retry_at=datetime.now(UTC))
    )
    s.commit()
    return res.rowcount


def run_due_jobs(ctx: ArchiveContext) -> dict[str, str]:
    with db.new_session() as s:
        ids = due_job_ids(s)
    return {jid: process_job(ctx, jid) for jid in ids}


class ArchiveWorker:
    """Single background thread; processes due jobs sequentially."""

    def __init__(self, ctx: ArchiveContext) -> None:
        self.ctx = ctx
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with db.new_session() as s:
            n = recover_interrupted(s)
        if n:
            log.info("recovered %d interrupted archive job(s)", n)
        self._thread = threading.Thread(target=self._run, name="archive-worker", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                run_due_jobs(self.ctx)
            except Exception:  # noqa: BLE001 — keep the worker alive; details are non-secret
                log.exception("archive worker iteration failed")
            self._wake.wait(timeout=self.ctx.settings.worker_poll_seconds)
            self._wake.clear()
