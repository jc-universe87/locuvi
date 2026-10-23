"""Sync as the rest of Locuvi uses it: numbering guard, background syncing, cloud folders."""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from locuvi import db
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.secrets_store import SecretBox
from locuvi.sync import engine
from locuvi.sync.merge import SyncConflict
from locuvi.sync.targets import TargetError

log = logging.getLogger("locuvi.sync")

EVERY_SECONDS = 300  # a quiet sync every five minutes
AFTER_CHANGE_SECONDS = 20  # and soon after something changes


@contextmanager
def numbering(settings: Settings, secrets: SecretBox) -> Iterator[None]:
    """Issue only after checking with the other devices, so numbers never clash.

    With sync off this does nothing. With sync on, a sync takes the numbering lease first;
    without a connection the issue waits (nothing is numbered), and the lease is handed back
    straight after.
    """
    if not engine.load_config(settings).enabled:
        yield
        return
    try:
        engine.sync_now(settings, secrets, lease=True)
    except TargetError:
        raise DomainError(
            "sync.issue_offline",
            "To issue, Locuvi first checks the next number with your other devices. Connect "
            "to the internet and try again. Your draft is saved.",
        ) from None
    except SyncConflict as exc:
        raise DomainError(exc.code, exc.message, **exc.details) from None
    try:
        yield
    finally:
        try:
            engine.sync_now(settings, secrets, release=True)
        except Exception as exc:  # noqa: BLE001 - the lease runs out by itself
            log.info("sync after issue failed: %s", type(exc).__name__)


class SyncWorker:
    """Background syncing for one profile (computers and servers; the phone app's own
    timer calls /api/v1/sync/now instead)."""

    def __init__(self, settings: Settings, secrets: SecretBox, profile_id: int) -> None:
        self.settings, self.secrets, self.profile_id = settings, secrets, profile_id
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._timer: threading.Timer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"sync-{self.profile_id}",
                                        daemon=True)  # fmt: skip
        self._thread.start()

    def nudge(self) -> None:
        """Something changed: sync soon (several changes in a row make one sync)."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(AFTER_CHANGE_SECONDS, self._wake.set)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._timer is not None:
            self._timer.cancel()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(EVERY_SECONDS)
            self._wake.clear()
            if self._stop.is_set():
                return
            if not engine.load_config(self.settings).enabled:
                continue
            try:
                with db.use_profile(self.profile_id):
                    engine.sync_now(self.settings, self.secrets)
            except (DomainError, TargetError, SyncConflict) as exc:
                log.info("sync: %s", exc.code)
            except Exception:  # noqa: BLE001 - keep the worker alive; the status shows it
                log.exception("sync failed")


def cloud_folders() -> list[dict[str, str]]:
    """Folders on this computer that a cloud app keeps in step, to choose with one tap."""
    home = Path.home()
    found: list[dict[str, str]] = []

    def add(name: str, path: Path) -> None:
        if path.is_dir() and all(f["path"] != str(path) for f in found):
            found.append({"name": name, "path": str(path)})

    cloud_storage = home / "Library" / "CloudStorage"  # macOS 12.5+
    if cloud_storage.is_dir():
        for d in sorted(cloud_storage.iterdir()):
            n = d.name.lower()
            if n.startswith("googledrive"):
                add("Google Drive", d / "My Drive" if (d / "My Drive").is_dir() else d)
            elif n.startswith("onedrive"):
                add("OneDrive", d)
            elif n.startswith("dropbox"):
                add("Dropbox", d)
    add("iCloud Drive", home / "Library" / "Mobile Documents" / "com~apple~CloudDocs")
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            add("OneDrive", Path(os.environ[env]))
    for name, rel in (
        ("Google Drive", "Google Drive/My Drive"),
        ("Google Drive", "My Drive"),
        ("Google Drive", "Google Drive"),
        ("OneDrive", "OneDrive"),
        ("Dropbox", "Dropbox"),
        ("iCloud Drive", "iCloudDrive"),
    ):
        add(name, home / rel)
    if sys.platform == "win32":
        for letter in "GHIJ":  # Google Drive for desktop mounts a drive letter
            add("Google Drive", Path(f"{letter}:/My Drive"))
    return found
