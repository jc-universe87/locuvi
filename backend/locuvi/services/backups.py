"""Automatic local backups into BACKUP_DIR (the /backups volume in Docker).

Archives contain bank details: copy them off the server encrypted (README "Backups").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.services import checks, core

log = logging.getLogger("locuvi.backups")


def backup_now(settings: Settings) -> dict:
    from locuvi import cli

    if settings.backup_dir is None:
        raise DomainError("backup.not_configured", "No backup folder is configured (BACKUP_DIR).")
    folder = Path(settings.backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).astimezone(core.LONDON).strftime("%Y-%m-%d-%H%M")
    dest = folder / f"locuvi-{stamp}.tar.gz"
    try:
        manifest = cli.backup(settings, dest)
    except SystemExit as exc:  # cli.backup reports integrity problems this way
        raise DomainError("backup.failed", str(exc)) from None
    pruned = prune(settings)
    log.info("backup written: %s (%d PDFs, pruned %d)", dest.name, manifest["issued_invoices"],
             pruned)  # fmt: skip
    return {"file": dest.name, "issued_invoices": manifest["issued_invoices"], "pruned": pruned}


def prune(settings: Settings) -> int:
    if settings.backup_dir is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=settings.backup_keep_days)
    n = 0
    for f in Path(settings.backup_dir).glob("locuvi-*.tar.gz"):
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
