"""Automatic backups: local into BACKUP_DIR, encrypted off-server copy, restore drill.

Archives contain bank details. With BACKUP_PASSPHRASE_FILE set, each backup is also encrypted
(backup_crypto) and uploaded to the Nextcloud/WebDAV target under BACKUP_REMOTE_PATH, never
overwriting and verified by SHA-256. After every backup a restore drill decrypts the newest
copy into a scratch folder and checks it; failures show on Today.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.services import checks, core
from locuvi.storage.local import sha256_bytes

log = logging.getLogger("locuvi.backups")


def backup_now(settings: Settings) -> dict:
    from locuvi import cli

    if settings.backup_dir is None:
        raise DomainError("backup.not_configured", "No backup folder is configured (BACKUP_DIR).")
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).astimezone(core.LONDON).strftime("%Y-%m-%d-%H%M%S")
    dest = folder / f"locuvi-{stamp}.tar.gz"
    try:
        manifest = cli.backup(settings, dest)
    except SystemExit as exc:  # cli.backup reports integrity problems this way
        raise DomainError("backup.failed", str(exc)) from None
    offsite = offsite_copy(settings, dest)
    drill = restore_drill(settings)
    pruned = prune(settings)
    log.info("backup written: %s (%d PDFs, pruned %d)", dest.name, manifest["issued_invoices"],
             pruned)  # fmt: skip
    return {
        "file": dest.name,
        "issued_invoices": manifest["issued_invoices"],
        "pruned": pruned,
        "offsite": offsite.get("status"),
        "drill_ok": drill["ok"],
    }


def before_upgrade(settings: Settings, engine: Any) -> Path | None:
    """Back up the database and PDFs before an update migrates them (needs BACKUP_DIR).

    If the copy cannot be made the upgrade is refused (raises), so the database is never
    migrated without a restorable copy. Go back to the previous image (LOCUVI_TAG) or fix the
    cause; LOCUVI_UPGRADE_WITHOUT_BACKUP=1 overrides this once, deliberately.
    """
    from locuvi import cli, migrate

    if settings.backup_dir is None:
        return None
    current, head = migrate.pending(engine)
    if current is None or current == head:
        return None  # new install, or nothing to migrate
    folder = Path(settings.backup_dir)
    stamp = datetime.now(UTC).astimezone(core.LONDON).strftime("%Y-%m-%d-%H%M%S")
    dest = folder / f"locuvi-{stamp}-before-{head}.tar.gz"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        cli.backup(settings, dest)
    except (SystemExit, Exception) as exc:  # noqa: BLE001
        log.error("backup before upgrade %s -> %s failed: %s", current, head, exc)
        if os.environ.get("LOCUVI_UPGRADE_WITHOUT_BACKUP") == "1":
            log.warning("LOCUVI_UPGRADE_WITHOUT_BACKUP=1: migrating without a backup")
            return None
        raise RuntimeError(
            f"Refusing to upgrade the database ({current} -> {head}) without a backup: {exc}. "
            "Fix the backup folder or the reported problem, or go back to the previous image."
        ) from None
    log.info("backup before upgrade %s -> %s written: %s", current, head, dest.name)
    return dest


# ------------------------------------------------------------------ off-server copy

OFFSITE_MARKER = ".offsite_backup.json"
DRILL_MARKER = ".restore_drill.json"


def _write_marker(settings: Settings, name: str, data: dict[str, Any]) -> None:
    try:
        (Path(settings.data_dir) / name).write_text(json.dumps(data))
    except OSError:
        log.warning("could not record %s", name)


def read_marker(settings: Settings, name: str) -> dict[str, Any] | None:
    try:
        data = json.loads((Path(settings.data_dir) / name).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def offsite_copy(settings: Settings, plain: Path) -> dict[str, Any]:
    """Encrypt `plain` next to it (.enc) and upload that to Nextcloud. Never raises: the local
    backup stands on its own; the outcome is recorded for Today."""
    from locuvi import backup_crypto, db
    from locuvi.secrets_store import SecretBox
    from locuvi.webdav import archive
    from locuvi.webdav.client import WebDavError
    from locuvi.webdav.urlguard import (
        InvalidPath,
        UrlBlocked,
        encode_path,
        validate_base_path,
        validate_base_url,
        validate_segment,
    )

    if not settings.backup_passphrase:
        return {"status": "off"}
    enc = plain.with_name(plain.name + ".enc")
    result: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "file": enc.name}
    try:
        backup_crypto.encrypt_file(plain, enc, settings.backup_passphrase)
    except (ValueError, OSError) as exc:
        result |= {"status": "failed", "error": "encrypt_failed"}
        log.warning("backup encryption failed: %s", type(exc).__name__)
        _write_marker(settings, OFFSITE_MARKER, result)
        return result
    ctx = archive.ArchiveContext(settings, SecretBox(settings))
    with db.new_session() as s:
        cfg = core.get_storage_config(s)
        enabled, url, user = cfg.enabled, cfg.target_url, cfg.username
        if not (enabled and url):
            result |= {"status": "local_only", "error": "webdav_not_configured"}
            _write_marker(settings, OFFSITE_MARKER, result)
            return result
        pw_error = "credentials_unavailable"
        try:
            pw = archive.get_password(ctx, cfg)
        except WebDavError as exc:
            pw, pw_error = "", exc.error_class
    try:
        if not pw:
            raise WebDavError(pw_error, "no app password")
        rel = encode_path(
            validate_base_path(settings.backup_remote_path) + [validate_segment(enc.name)]
        )
        data = enc.read_bytes()
        sha = sha256_bytes(data)
        vurl = validate_base_url(url, settings)
        with archive._client(ctx, vurl, user, pw) as c:
            archive.upload_verified(c, rel, data, sha, "backup", "application/octet-stream")
        result |= {"status": "synced", "remote": rel, "sha256": sha}
    except (WebDavError, UrlBlocked, InvalidPath, OSError) as exc:
        err = getattr(exc, "error_class", None) or type(exc).__name__
        result |= {"status": "failed", "error": err}
        log.warning("off-server backup copy failed: %s", err)
    _write_marker(settings, OFFSITE_MARKER, result)
    return result


def latest_backup(settings: Settings) -> Path | None:
    """Newest backup, preferring the encrypted off-server copy when there is one."""
    if settings.backup_dir is None:
        return None
    files = sorted(Path(settings.backup_dir).glob("locuvi-*.tar.gz*"),
                   key=lambda f: f.stat().st_mtime, reverse=True)  # fmt: skip
    files = [f for f in files if not f.name.endswith(".partial")]
    if not files:
        return None
    newest = files[0].name.removesuffix(".enc")
    enc = Path(settings.backup_dir) / (newest + ".enc")
    return enc if enc.exists() else Path(settings.backup_dir) / newest


def restore_drill(
    settings: Settings, src: Path | None = None, passphrase: str | None = None
) -> dict[str, Any]:
    """Prove the newest backup restores: decrypt, extract to scratch, check every checksum,
    the database and the counts. Live data is never touched. Recorded for Today."""
    from locuvi import cli

    src = src or latest_backup(settings)
    result: dict[str, Any] = {"at": datetime.now(UTC).isoformat(), "ok": False}
    if src is None:
        result["error"] = "no backup found"
        return result
    result["file"] = src.name
    try:
        manifest = cli.check_backup(src, passphrase or settings.backup_passphrase)
        result |= {
            "ok": True,
            "encrypted": src.name.endswith(".enc"),
            "issued_invoices": manifest["issued_invoices"],
            "credit_notes": manifest.get("credit_notes", 0),
        }
    except SystemExit as exc:
        result["error"] = str(exc)
        log.warning("restore drill failed for %s: %s", src.name, exc)
    _write_marker(settings, DRILL_MARKER, result)
    return result


def prune(settings: Settings) -> int:
    if settings.backup_dir is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=settings.backup_keep_days)
    n = 0
    for f in Path(settings.backup_dir).glob("locuvi-*.tar.gz*"):
        if datetime.fromtimestamp(f.stat().st_mtime, UTC) < cutoff:
            f.unlink(missing_ok=True)
            n += 1
    return n


def nightly_due(settings: Settings, now: datetime | None = None) -> bool:
    """After 02:00 London, once per day, when a backup folder is configured."""
    if settings.backup_dir is None:
        return False
    local = (now or datetime.now(UTC)).astimezone(core.LONDON)
    if local.hour < 2:
        return False
    last = checks.last_backup_at(settings)
    return last is None or last.astimezone(core.LONDON).date() < local.date()
