"""Routes used only by the Windows and macOS app (see ``locuvi.desktop``)."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from locuvi import desktop
from locuvi.api import schemas as S
from locuvi.api.routes import _admin, _set_cookie, api
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
    cfg["phone_access"] = body.phone_access
    desktop.write_config(settings.desktop_config, cfg)
    return _state(request)
