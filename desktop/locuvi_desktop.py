"""Locuvi for Windows and macOS: the full Locuvi, running on this computer.

What it does when you open it:

1. Keeps your records in your own user folder (Windows: %LOCALAPPDATA%\\Locuvi, macOS:
   ~/Library/Application Support/Locuvi), with nightly backups in its ``backups`` folder.
2. Starts Locuvi on this computer only (127.0.0.1), or on your home network too if you
   switched on "Let my phone and tablet connect" (Settings › Phones, tablets and computers).
3. Opens Locuvi in its own window (Microsoft Edge or Google Chrome app window, else your
   browser), already signed in for this launch.
4. Stops by itself a few minutes after you close that window, after a last sync (unless
   phone access is on: then it keeps running so your phone can connect). Settings › Phones,
   tablets and computers has Quit Locuvi and Show my Locuvi folder.

Opening it again while it's running just opens another Locuvi window.

New versions (Settings › Phones, tablets and computers › Updates, on unless switched off):
while Locuvi runs it looks for one now and then and downloads it; when Locuvi stops, the
new version is installed, so it's new the next time it opens. If Locuvi keeps running for
phones and tablets, it installs at night once nobody has had its window open for a while,
and starts again without a window (``--no-window``).

``--headless`` starts Locuvi without any windows and writes its address to ``--info-file``;
the release workflow uses it to test the packaged app on Windows and macOS.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "Locuvi"
log = logging.getLogger("locuvi.desktop")


# ------------------------------------------------------------------------ paths


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path | None:
    # built web app: frontend/dist in the source tree, frontend/ inside the packaged app
    for c in (bundle_dir() / "frontend" / "dist", bundle_dir() / "frontend"):
        if (c / "index.html").is_file() and (c / "assets").is_dir():
            return c
    return None


def data_root(override: str | None) -> Path:
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP


def _private_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ----------------------------------------------------------------- one at a time


def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=2):
            return True
    except OSError:
        return False


def running_instance(root: Path) -> dict | None:
    """The details of a Locuvi already running from this folder, or None."""
    f = root / "instance.json"
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info.get("port"), int) and _alive(info["port"]) else None


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(host: str, preferred: int, fixed: bool) -> int:
    if _port_free(host, preferred):
        return preferred
    if fixed:  # phones expect this address
        raise RuntimeError(
            f"Port {preferred} is in use by another program, so phones can't connect. "
            "Close that program, or switch phone access off, and open Locuvi again."
        )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- open a window


def _app_browsers() -> list[str]:
    """Chromium browsers that can show Locuvi in its own app window."""
    found: list[str] = []
    if sys.platform == "win32":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        found += [str(Path(r) / x) for x in rel for r in roots if r and (Path(r) / x).is_file()]
        found += [p for p in (shutil.which("msedge"), shutil.which("chrome")) if p]
    elif sys.platform == "darwin":
        for name in ("Google Chrome", "Microsoft Edge"):
            for base in ("/Applications", str(Path.home() / "Applications")):
                exe = Path(base) / f"{name}.app" / "Contents" / "MacOS" / name
                if exe.is_file():
                    found.append(str(exe))
    else:
        found += [p for p in (shutil.which(n) for n in ("google-chrome", "chromium", "msedge")) if p]
    return list(dict.fromkeys(found))


def open_window(url: str) -> None:
    for exe in _app_browsers():
        try:
            subprocess.Popen([exe, f"--app={url}", "--new-window"],  # noqa: S603
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
            return
        except OSError:
            continue
    webbrowser.open(url)


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


# ---------------------------------------------------------------------- server


class Locuvi:
    def __init__(self, root: Path, password_file: Path | None = None, port: int | None = None):
        self.root = root
        for d in ("data", "keys", "backups", "logs"):
            (root / d).mkdir(parents=True, exist_ok=True)
        if password_file is None:
            # Starts with a random password nobody knows: this computer's window signs in with
            # a launch token instead, and the owner picks their own password before letting
            # phones connect.
            password_file = root / "keys" / "desktop-password"
            if not password_file.is_file():
                _private_file(password_file, secrets.token_urlsafe(24))
        self.config_file = root / "desktop.json"
        from_cfg = self._config()
        self.phone_access = bool(from_cfg["phone_access"])
        self.host = "0.0.0.0" if self.phone_access else "127.0.0.1"  # noqa: S104 - opt-in
        self.port = port or choose_port(self.host, from_cfg["port"], fixed=self.phone_access)
        self.token = secrets.token_urlsafe(32)
        static = static_dir()
        os.environ.update({
            "APP_ENV": "production",
            "DATA_DIR": str(root / "data"),
            "KEY_DIR": str(root / "keys"),
            "BACKUP_DIR": str(root / "backups"),
            "LOCUVI_PASSWORD_FILE": str(password_file),
            "COOKIE_SECURE": "false",  # plain http on this computer / home network
            "LOCUVI_DESKTOP": "1",
            "LOCUVI_DESKTOP_TOKEN": self.token,
            "LOCUVI_DESKTOP_CONFIG": str(self.config_file),
            "LOCUVI_DESKTOP_HOST": self.host,
            "LOCUVI_DESKTOP_PORT": str(self.port),
        })  # fmt: skip
        if static:
            os.environ["STATIC_DIR"] = str(static)
        self.server = None
        self.thread: threading.Thread | None = None

    def _config(self) -> dict:
        sys.path.insert(0, str(bundle_dir() / "backend"))
        from locuvi import desktop

        return desktop.read_config(self.config_file)

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def open_url(self) -> str:
        return f"{self.local_url}/desktop/open?token={self.token}"

    def start(self, timeout: float = 60) -> None:
        import uvicorn

        from locuvi.main import create_app

        app = create_app()
        cfg = uvicorn.Config(app, host=self.host, port=self.port, log_level="warning",
                             access_log=False, log_config=None)  # fmt: skip
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, name="locuvi", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started and _alive(self.port):
                _private_file(self.root / "instance.json",
                              json.dumps({"port": self.port, "token": self.token, "pid": os.getpid()}))  # fmt: skip
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.2)
        raise RuntimeError("Locuvi didn't start. See the log in the Locuvi folder.")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=20)
        try:
            (self.root / "instance.json").unlink()
        except OSError:
            pass

    def addresses(self) -> list[str]:
        if not self.phone_access:
            return []
        from locuvi import desktop

        return [f"http://{ip}:{self.port}" for ip in desktop.local_addresses()]


# ---------------------------------------------------------------- staying open


PREPARE_EVERY = 30 * 60  # look for (and download) a new version this often while running


def update_by_itself(app: Locuvi) -> bool:
    """The owner's choice in Settings › Updates (read each time, so switching it off counts)."""
    from locuvi import desktop

    return bool(desktop.read_config(app.config_file)["update_check"])


class Updater:
    """Downloads a new version in the background while Locuvi runs (``updates.prepare``)."""

    def __init__(self, app: Locuvi) -> None:
        self.app = app
        self.folder = app.root / "updates"
        self.last = -PREPARE_EVERY
        self.thread: threading.Thread | None = None

    def _prepare(self) -> None:
        from locuvi import updates

        try:
            updates.prepare(self.folder)
        except Exception as exc:  # noqa: BLE001 - tried again later
            log.info("looking for a new version failed: %s", type(exc).__name__)

    def tick(self, now: float) -> None:
        if now - self.last < PREPARE_EVERY or (self.thread and self.thread.is_alive()):
            return
        self.last = now
        if update_by_itself(self.app):
            self.thread = threading.Thread(target=self._prepare, name="locuvi-update", daemon=True)
            self.thread.start()


def run_until_done(app: Locuvi, updater: Updater | None = None) -> str:
    """Keep Locuvi running while its window is open (or phone access is on), then stop.

    There's no extra window to keep open: see ``locuvi.desktop.should_stop``. Opening Locuvi
    again while it runs just opens another window (``running_instance``). Returns "update"
    when it stops to install a new version while running for phones, else "closed".
    """
    from locuvi import desktop, updates

    started = time.monotonic()
    while app.thread and app.thread.is_alive():
        now = time.monotonic()
        if desktop.should_stop(now, started, app.phone_access):
            log.info("Locuvi's window was closed (or Quit chosen): stopping")
            return "closed"
        if updater is not None:
            updater.tick(now)
            idle = now - (desktop.last_seen() or started)
            if (app.phone_access and updates.ready_file() is not None
                    and updates.due_while_running(idle, time.localtime().tm_hour)
                    and update_by_itself(app)):  # fmt: skip
                log.info("installing a new version while nobody is using Locuvi")
                return "update"
        time.sleep(2)
    return "closed"


def install_new_version(app: Locuvi, reopen: list[str] | None) -> None:
    """Locuvi has stopped: install the new version downloaded earlier, if there is one."""
    from locuvi import updates

    try:
        if update_by_itself(app) and updates.install_on_exit(reopen):
            log.info("a new version installs now that Locuvi has stopped")
    except Exception:  # noqa: BLE001 - it tries again next time
        log.exception("the new version couldn't be installed")


def last_sync() -> None:
    """Before stopping, send the latest changes to the sync folder (if sync is on)."""
    try:
        from locuvi.config import Settings
        from locuvi.secrets_store import SecretBox
        from locuvi.sync import engine

        st = Settings.from_env()
        if engine.load_config(st).enabled:
            engine.sync_now(st, SecretBox(st))
    except Exception as exc:  # noqa: BLE001 - next start syncs again
        log.info("last sync before stopping didn't finish: %s", type(exc).__name__)


def error_box(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP, message)
        r.destroy()
    except Exception:  # noqa: BLE001 - no display at all: the log has it
        pass


# ------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="Locuvi")
    ap.add_argument("--data-dir", help="keep records here instead of the usual folder")
    ap.add_argument("--headless", action="store_true", help="no windows (for testing)")
    ap.add_argument("--info-file", help="write the address here once Locuvi is running")
    ap.add_argument("--password-file", help="use this password instead of a random one")
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-window", action="store_true", help="start without opening a window")
    ap.add_argument(
        "--update-on-exit",
        action="store_true",
        help="with --headless: download a new version, install it on Quit (tests)",
    )
    args, _unknown = ap.parse_known_args(argv)  # macOS may add -psn_… arguments

    root = data_root(args.data_dir)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(root / "logs" / "locuvi.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )  # fmt: skip

    existing = running_instance(root)
    if existing and not args.headless:
        if args.no_window:
            return 0
        open_window(f"http://127.0.0.1:{existing['port']}/desktop/open?token={existing['token']}")
        return 0

    try:
        app = Locuvi(root, Path(args.password_file) if args.password_file else None, args.port)
        app.start()
    except Exception as exc:  # noqa: BLE001 - shown to the person, then logged
        log.exception("Locuvi did not start")
        if not args.headless:
            error_box(f"Locuvi couldn't start.\n\n{exc}\n\nDetails: {root / 'logs' / 'locuvi.log'}")
        return 1
    log.info("Locuvi running on %s:%s", app.host, app.port)
    if args.info_file:
        Path(args.info_file).write_text(
            json.dumps({"url": app.local_url, "open": app.open_url, "root": str(root)}),
            encoding="utf-8",
        )
    stopped = None
    try:
        if args.headless:
            from locuvi import desktop

            if args.update_on_exit:
                Updater(app)._prepare()
            # runs until stopped from outside, or Quit (also when an update installs)
            while app.thread and app.thread.is_alive() and not desktop.should_stop(0, 0, True):
                time.sleep(0.5)
            stopped = "closed" if args.update_on_exit else None
        else:
            if not args.no_window:
                open_window(app.open_url)
            stopped = run_until_done(app, Updater(app))
            last_sync()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    if stopped:
        install_new_version(app, ["--no-window"] if stopped == "update" else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
