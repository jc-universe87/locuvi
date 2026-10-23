"""Sync between devices, and the one-file export (``locuvi.sync``)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import File, Form, Request, Response, UploadFile

from locuvi.api import schemas as S
from locuvi.api.routes import api, state
from locuvi.errors import DomainError
from locuvi.sync import engine, service

MAX_IMPORT = 2 * 1024 * 1024 * 1024  # 2 GB


def _ctx(request: Request) -> tuple[Any, Any]:
    app = state(request)
    return app.settings, request.app.state.secrets


def _where(request: Request, body: S.SyncWhereIn) -> dict[str, Any]:
    if body.kind == "nextcloud":
        return {"kind": "nextcloud"}
    path = Path((body.path or "").strip()).expanduser()
    if not body.path or not path.is_absolute() or not path.is_dir():
        raise DomainError("sync.folder_missing", "Choose a folder that exists on this computer.")
    return {"kind": "folder", "path": str(path)}


@api.get("/sync")
def sync_status(request: Request) -> dict[str, Any]:
    settings, _ = _ctx(request)
    out = engine.status(settings)
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
