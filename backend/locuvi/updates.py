"""New versions of the Windows and Mac app: check, download, install (``/api/v1/updates``).

The release workflow writes the version it builds into ``locuvi/_release.py``; a Locuvi
without that file (a server, or run from the code) doesn't update itself. The check asks
GitHub for the latest release, at most every few hours, and only ever downloads that
release's own installer, checked against the SHA-256 GitHub lists for it.

Installing waits for Locuvi to stop (after a last sync), then:

- Windows: runs the installer silently over the old version and opens Locuvi again;
- Mac: replaces Locuvi.app with the one in the new disk image and opens it again.

Records live in the Locuvi folder, not in the app, so they're untouched; Locuvi also makes a
backup before migrating on its next start.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from locuvi.errors import DomainError

log = logging.getLogger("locuvi.updates")

LATEST = os.environ.get(
    "LOCUVI_UPDATE_URL", "https://api.github.com/repos/jc-universe87/locuvi/releases/latest"
)
CHECK_EVERY = 6 * 3600
ASSETS = {"win32": "Locuvi-Windows-Setup.exe", "darwin": "Locuvi-macOS.dmg"}
MAX_SIZE = 400 * 1024 * 1024

_cache: dict[str, Any] = {"at": 0.0, "info": None}
_lock = threading.Lock()


def current_version() -> str | None:
    """The released version this app was built as, or None (not a released app)."""
    try:
        from locuvi import _release  # type: ignore[attr-defined]  # written by the release build
    except ImportError:
        return None
    return str(_release.VERSION) or None


def parse(version: str) -> tuple[int, ...]:
    """ "v1.1.16" → (1, 1, 16). Anything else compares as oldest."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


@dataclass
class Update:
    version: str
    url: str
    size: int
    sha256: str
    notes: str


def _latest(client: httpx.Client | None = None) -> Update | None:
    asset_name = ASSETS.get(sys.platform)
    if asset_name is None:
        return None
    http = client or httpx.Client(timeout=15, follow_redirects=True)
    try:
        r = http.get(LATEST, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()
    finally:
        if client is None:
            http.close()
    for a in data.get("assets") or []:
        digest = str(a.get("digest") or "")
        if a.get("name") == asset_name and digest.startswith("sha256:"):
            return Update(
                version=str(data.get("tag_name", "")).lstrip("v"),
                url=str(a["browser_download_url"]),
                size=int(a.get("size") or 0),
                sha256=digest.removeprefix("sha256:").lower(),
                notes=str(data.get("html_url") or ""),
            )
    return None


def check(
    *, force: bool = False, offline: bool = False, client: httpx.Client | None = None
) -> dict[str, Any]:
    """What this app knows about updates: ``{"supported", "current", "latest", "available"}``."""
    current = current_version()
    out: dict[str, Any] = {"supported": bool(current and sys.platform in ASSETS),
                           "current": current, "latest": None, "available": False}  # fmt: skip
    if not out["supported"]:
        return out
    with _lock:
        if force or (not offline and time.time() - _cache["at"] > CHECK_EVERY):
            try:
                _cache["info"] = _latest(client)
                _cache["at"] = time.time()
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.info("update check failed: %s", type(exc).__name__)
                out["error"] = True
        info: Update | None = _cache["info"]
    if info:
        out["latest"] = info.version
        out["available"] = parse(info.version) > parse(current or "")
        out["notes"] = info.notes
    return out


def _bad_file() -> DomainError:
    return DomainError("updates.bad_file", "The update didn't look right, so it wasn't installed.")


def download(folder: Path, client: httpx.Client | None = None) -> Path:
    """Fetch the latest installer into ``folder`` and check it is exactly the released file."""
    info: Update | None = _cache["info"]
    if info is None or not check()["available"]:
        raise DomainError("updates.none", "You already have the latest Locuvi.")
    if info.size > MAX_SIZE:
        raise _bad_file()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / ASSETS[sys.platform]
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    http = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        with http.stream("GET", info.url) as r, part.open("wb") as fh:
            r.raise_for_status()
            total = 0
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > MAX_SIZE:
                    raise _bad_file()
                h.update(chunk)
                fh.write(chunk)
    except httpx.HTTPError:
        part.unlink(missing_ok=True)
        raise DomainError(
            "updates.offline", "The update couldn't be downloaded. Check your internet connection."
        ) from None
    finally:
        if client is None:
            http.close()
    if h.hexdigest() != info.sha256:
        part.unlink(missing_ok=True)
        raise _bad_file()
    os.replace(part, dest)
    return dest


def app_bundle() -> Path | None:
    """The Locuvi.app (Mac) or folder with Locuvi.exe (Windows) that is running now."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        return None
    return exe.parent


def install_command(installer: Path, bundle: Path, pid: int) -> list[str]:
    """The detached command that installs once Locuvi (process ``pid``) has stopped, then
    opens it again."""
    if sys.platform == "win32":
        exe = bundle / "Locuvi.exe"
        script = (
            f"Wait-Process -Id {pid} -Timeout 120 -ErrorAction SilentlyContinue; "
            f"Start-Process -Wait -FilePath '{installer}' -ArgumentList "
            "'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER'; "
            f"Start-Process -FilePath '{exe}'"
        )
        return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script]
    mnt = installer.with_suffix(".mnt")
    script = (
        f"for i in $(seq 120); do kill -0 {pid} 2>/dev/null || break; sleep 1; done; "
        f'hdiutil attach -nobrowse -noverify -mountpoint "{mnt}" "{installer}" && '
        f'rm -rf "{bundle}.old" && mv "{bundle}" "{bundle}.old" && '
        f'ditto "{mnt}/Locuvi.app" "{bundle}" && rm -rf "{bundle}.old"; '
        f'hdiutil detach "{mnt}" -quiet; '
        f'if [ ! -d "{bundle}" ] && [ -d "{bundle}.old" ]; then mv "{bundle}.old" "{bundle}"; fi; '
        f'open "{bundle}"'
    )
    return ["/bin/sh", "-c", script]


def start_install(folder: Path) -> None:
    """Download and check the update, then hand over to the installer and let Locuvi stop."""
    bundle = app_bundle()
    if bundle is None:
        raise DomainError(
            "updates.not_app", "Only the Locuvi app for Windows and Mac updates itself."
        )
    if sys.platform == "darwin" and (
        str(bundle).startswith("/Volumes/") or not os.access(bundle.parent, os.W_OK)
    ):
        raise DomainError(
            "updates.mac_move",
            "Move Locuvi into your Applications folder first (drag it from the disk image), "
            "then open it from there.",
        )
    installer = download(folder)
    cmd = install_command(installer, bundle, os.getpid())
    kw: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                          "stderr": subprocess.DEVNULL, "close_fds": True}  # fmt: skip
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)  # noqa: S603 - fixed command, our own verified installer
    log.info("installing Locuvi %s", _cache["info"].version)

    from locuvi import desktop

    desktop.ask_to_quit()
