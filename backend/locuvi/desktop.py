"""Support for the Windows and macOS app (desktop/locuvi_desktop.py).

The app runs this same Locuvi on the owner's computer. Two things differ from a server:

- Its own window opens already signed in, through ``/desktop/open?token=…``. The token is
  random for each launch and only the app knows it.
- Phones and tablets can be allowed to connect over the home network ("phone access"). That
  is off by default, needs the owner's own password first (the app starts with a random one
  nobody knows), and takes effect when the app restarts, because the app then listens on the
  network instead of only on this computer.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8765


def read_config(path: Path | None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if path and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    port = data.get("port")
    return {
        "phone_access": bool(data.get("phone_access", False)),
        "port": port if isinstance(port, int) and 1024 <= port <= 65535 else DEFAULT_PORT,
    }


def write_config(path: Path, cfg: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def local_addresses() -> list[str]:
    """This computer's IPv4 addresses on its networks (home Wi-Fi, Tailscale), best first."""
    found: list[str] = []

    def add(ip: str) -> None:
        if ip and not ip.startswith(("127.", "169.254.")) and ip not in found:
            found.append(ip)

    try:  # the address used to reach the internet: usually the home network one
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address: nothing is sent
            add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(str(info[4][0]))
    except OSError:
        pass
    return found
