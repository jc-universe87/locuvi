"""Locuvi for Windows and macOS: the full Locuvi, running on this computer.

What it does when you open it:

1. Keeps your records in your own user folder (Windows: %LOCALAPPDATA%\\Locuvi, macOS:
   ~/Library/Application Support/Locuvi), with nightly backups in its ``backups`` folder.
2. Starts Locuvi on this computer only (127.0.0.1), or on your home network too if you
   switched on "Let my phone and tablet connect" (Settings › Phones, tablets and computers).
3. Opens Locuvi in its own window (Microsoft Edge or Google Chrome app window, else your
   browser), already signed in for this launch.
4. Shows a small "Locuvi is running" window. Closing it stops Locuvi.

Opening it again while it's running just opens another Locuvi window.

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


# ------------------------------------------------------------- control window


def control_window(app: Locuvi) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(APP)
    root.resizable(False, False)
    try:
        icon = bundle_dir() / "desktop" / "assets" / "locuvi.png"
        if icon.is_file():
            root.iconphoto(True, tk.PhotoImage(file=str(icon)))
    except tk.TclError:
        pass
    frame = ttk.Frame(root, padding=18)
    frame.grid()
    ttk.Label(frame, text="Locuvi is running on this computer.", font=("", 13, "bold")).grid(
        sticky="w"
    )
    ttk.Label(frame, text="Keep this window open while you use Locuvi.\nClosing it stops Locuvi.",
              justify="left").grid(sticky="w", pady=(4, 10))  # fmt: skip
    ttk.Button(frame, text="Open Locuvi", command=lambda: open_window(app.open_url)).grid(
        sticky="we"
    )
    addrs = app.addresses()
    if addrs:
        ttk.Label(frame, text="Phones and tablets on your network can use:",
                  justify="left").grid(sticky="w", pady=(12, 2))  # fmt: skip
        for a in addrs:
            ttk.Label(frame, text=a, font=("Courier", 11)).grid(sticky="w")
    ttk.Button(frame, text="Show my Locuvi folder", command=lambda: open_folder(app.root)).grid(
        sticky="we", pady=(12, 0)
    )

    def quit_app() -> None:
        root.destroy()

    ttk.Button(frame, text="Quit Locuvi", command=quit_app).grid(sticky="we", pady=(6, 0))
    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()


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
    args, _unknown = ap.parse_known_args(argv)  # macOS may add -psn_… arguments

    root = data_root(args.data_dir)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(root / "logs" / "locuvi.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )  # fmt: skip

    existing = running_instance(root)
    if existing and not args.headless:
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
    try:
        if args.headless:
            while app.thread and app.thread.is_alive():
                time.sleep(0.5)
        else:
            open_window(app.open_url)
            control_window(app)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
