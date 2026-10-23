"""Sync between devices, and the one-file export (``locuvi.sync``)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import File, Form, Request, Response, UploadFile

from locuvi.api import schemas as S
from locuvi.api.routes import api, state
from locuvi.errors import DomainError
from locuvi.sync import cloud, engine, service

MAX_IMPORT = 2 * 1024 * 1024 * 1024  # 2 GB


def _ctx(request: Request) -> tuple[Any, Any]:
    app = state(request)
    return app.settings, request.app.state.secrets


def _where(request: Request, body: S.SyncWhereIn) -> dict[str, Any]:
    if body.kind == "cloud":
        settings, _ = _ctx(request)
        return engine.cloud_spec(settings, body.connection or "")
    if body.kind == "nextcloud":
        settings, secrets = _ctx(request)
        if not body.url:
            raise DomainError("sync.nextcloud_url", "Type your Nextcloud's address.")
        return engine.nextcloud_spec(
            settings,
            secrets,
            url=body.url,
            home_url=body.home_url,
            username=body.username or "",
            password=body.password,
        )
    path = Path((body.path or "").strip()).expanduser()
    if not body.path or not path.is_absolute() or not path.is_dir():
        raise DomainError("sync.folder_missing", "Choose a folder that exists on this computer.")
    return {"kind": "folder", "path": str(path)}


@api.get("/sync")
def sync_status(request: Request) -> dict[str, Any]:
    settings, secrets = _ctx(request)
    out = engine.status(settings)
    out["nextcloud_saved"] = engine.saved_nextcloud_hint(settings, secrets)
    # signing in can only come back to the Windows/Mac app, the Android app or the iPhone
    # site (cloud._check_return), not to a Locuvi on a server
    on_device = request.app.state.settings.desktop or os.environ.get("LOCUVI_POCKET") == "1"
    out["cloud_accounts"] = cloud.available() if on_device else []
    out["cloud_folders"] = service.cloud_folders() if request.app.state.settings.desktop else []
    out["can_choose_folder"] = bool(request.app.state.settings.desktop)
    return out


@api.post("/sync/start")
def sync_start(body: S.SyncWhereIn, request: Request) -> dict[str, Any]:
    settings, secrets = _ctx(request)
    code = engine.start(settings, secrets, _where(request, body), body.device_name)
    return {**engine.status(settings), "code": code}


@api.post("/sync/join")
def sync_join(body: S.SyncJoinIn, request: Request) -> dict[str, Any]:
    settings, secrets = _ctx(request)
    report = engine.join(settings, secrets, _where(request, body), body.device_name, body.code)
    return {**engine.status(settings), "pulled": report.pulled}


@api.post("/sync/now")
def sync_now(request: Request) -> dict[str, Any]:
    settings, secrets = _ctx(request)
    report = engine.sync_now(settings, secrets)
    return {**engine.status(settings), "pulled": report.pulled}


@api.get("/sync/code")
def sync_code(request: Request) -> dict[str, Any]:
    settings, secrets = _ctx(request)
    return {"code": engine.code_for_display(settings, secrets)}


@api.post("/sync/stop")
def sync_stop(request: Request) -> dict[str, Any]:
    settings, _ = _ctx(request)
    engine.stop(settings)
    return engine.status(settings)


@api.post("/sync/export")
def sync_export(body: S.SyncExportIn, request: Request) -> Response:
    settings, _ = _ctx(request)
    data = engine.export_everything(settings, body.passphrase)
    name = f"Locuvi-everything-{date.today().isoformat()}.locuvi"
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@api.post("/sync/import")
async def sync_import(
    request: Request,
    file: Annotated[UploadFile, File()],
    passphrase: Annotated[str, Form(max_length=200)],
) -> dict[str, Any]:
    settings, _ = _ctx(request)
    data = await file.read(MAX_IMPORT + 1)
    if len(data) > MAX_IMPORT:
        raise DomainError("sync.import_too_large", "That file is too large.")
    return {"brought": engine.import_everything(settings, data, passphrase)}


@api.post("/sync/cloud/begin")
def cloud_begin(body: S.CloudBeginIn) -> dict[str, str]:
    """Where to sign in to Dropbox, Google Drive or OneDrive (see ``locuvi.sync.cloud``)."""
    return cloud.begin(body.provider, body.return_to)


@api.post("/sync/cloud/finish")
def cloud_finish(body: S.CloudFinishIn, request: Request) -> dict[str, str]:
    """Back from signing in: keep the sign-in for Start or Join (``connection``)."""
    settings, secrets = _ctx(request)
    result = cloud.finish(body.provider, body.code, body.verifier, body.return_to)
    connection = engine.cloud_connected(settings, secrets, result)
    return {"connection": connection, "provider": body.provider, "account": result["account"]}
