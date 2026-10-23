"""Routes used only by the Windows and macOS app (see ``locuvi.desktop``)."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from locuvi import desktop
from locuvi.api import schemas as S
from locuvi.api.routes import _admin, _set_cookie, api, public
from locuvi.errors import DomainError, NotFound

opener = APIRouter()


@opener.get("/desktop/open", include_in_schema=False)
def desktop_open(request: Request, token: str = "") -> RedirectResponse:
    """The app's own window: sign in without a password, with this launch's secret token."""
    from locuvi import profiles

    settings = request.app.state.settings
    response = RedirectResponse("/", status_code=303)
    expected = settings.desktop_token
    if not (settings.desktop and expected and hmac.compare_digest(token, expected)):
        return response  # wrong or no token: the normal sign-in page
    people = profiles.all_profiles(settings)
    if len(people) == 1:  # several household profiles: each signs in with their own password
        _set_cookie(request, response, request.app.state.sessions.issue_token(people[0]))
    return response


def _state(request: Request) -> dict[str, Any]:
    from locuvi.api.auth import verify_password

    settings = request.app.state.settings
    if not settings.desktop:
        return {"available": False}
    cfg = desktop.read_config(settings.desktop_config)
    me = request.state.profile
    own_password = not (
        settings.password
        and me.password_hash
        and verify_password(settings.password, me.password_hash)
    )
    listening = os.environ.get("LOCUVI_DESKTOP_HOST") == "0.0.0.0"
    port = int(os.environ.get("LOCUVI_DESKTOP_PORT") or cfg["port"])
    return {
        "available": True,
        "phone_access": cfg["phone_access"],
        "update_check": cfg["update_check"],
        "keeps_running": listening,  # after its window closes, so phones can connect
        "listening": listening,
        "restart_needed": cfg["phone_access"] != listening,
        "own_password": own_password,
        "addresses": [f"http://{ip}:{port}" for ip in desktop.local_addresses()]
        if listening
        else [],
    }


@api.get("/desktop")
def get_desktop(request: Request) -> dict[str, Any]:
    return _state(request)


@api.put("/desktop")
def put_desktop(body: S.DesktopIn, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.desktop or settings.desktop_config is None:
        raise NotFound("desktop.not_available", "Only the Locuvi app on a computer has this.")
    _admin(request)
    if body.phone_access and not _state(request)["own_password"]:
        raise DomainError(
            "desktop.set_password_first",
            "Choose your own password first (Settings › Password); phones sign in with it.",
        )
    cfg = desktop.read_config(settings.desktop_config)
    if body.phone_access is not None:
        cfg["phone_access"] = body.phone_access
    if body.update_check is not None:
        cfg["update_check"] = body.update_check
    desktop.write_config(settings.desktop_config, cfg)
    return _state(request)


def _desktop_only(request: Request) -> Any:
    settings = request.app.state.settings
    if not settings.desktop:
        raise NotFound("desktop.not_available", "Only the Locuvi app on a computer has this.")
    return settings


@public.post("/desktop/alive")
def desktop_alive(request: Request) -> dict[str, bool]:
    """The app's window is still open (see ``desktop.should_stop``).

    No sign-in needed: it only keeps Locuvi running, and a beat sent just as someone signs
    out (or in as another household profile) must not fail. Only from this computer."""
    import time

    _desktop_only(request)
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise NotFound("desktop.not_available", "Only on the computer Locuvi runs on.")
    desktop.seen(time.monotonic())
    return {"ok": True}


@api.post("/desktop/quit")
def desktop_quit(request: Request) -> dict[str, bool]:
    """Stop Locuvi on this computer (after a last sync)."""
    _desktop_only(request)
    desktop.ask_to_quit()
    return {"ok": True}


@api.post("/desktop/open-folder")
def desktop_open_folder(request: Request) -> dict[str, bool]:
    """Show the Locuvi folder (records, backups, log) in Explorer or Finder."""
    import subprocess
    import sys
    from pathlib import Path

    settings = _desktop_only(request)
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise NotFound("desktop.not_available", "Only on the computer Locuvi runs on.")
    folder = Path(settings.data_dir).parent
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603, S607
    return {"ok": True}


# ------------------------------------------------------------------ new versions


@api.get("/updates")
def get_updates(request: Request, check: bool = False) -> dict[str, Any]:
    """Is there a newer Locuvi? On its own at most every few hours (if allowed), or now."""
    from locuvi import updates

    settings = request.app.state.settings
    if not settings.desktop:
        return {"supported": False}
    if not check and not desktop.read_config(settings.desktop_config)["update_check"]:
        return {**updates.check(offline=True), "automatic": False}
    return {**updates.check(force=check), "automatic": True}


@api.post("/updates/install")
def install_update(request: Request) -> dict[str, bool]:
    """Download the new version, check it, install it and open Locuvi again."""
    from pathlib import Path

    from locuvi import updates

    settings = _desktop_only(request)
    _admin(request)
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise NotFound("desktop.not_available", "Only on the computer Locuvi runs on.")
    updates.start_install(Path(settings.data_dir).parent / "updates")
    return {"ok": True}
