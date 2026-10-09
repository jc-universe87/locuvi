"""FastAPI application factory. Serves the API and the built frontend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from locuvi import __version__, db, integrity, profiles
from locuvi.api import inbox as _inbox  # registers routes on `api`; `feeds` is public
from locuvi.api.auth import SessionManager
from locuvi.api.mcp import router as mcp_router
from locuvi.api.routes import api, public
from locuvi.config import Settings, get_settings
from locuvi.errors import DomainError
from locuvi.migrate import upgrade
from locuvi.secrets_store import SecretBox, ensure_dir_private
from locuvi.services import core
from locuvi.services.digest import DigestScheduler
from locuvi.webdav.archive import ArchiveContext, ArchiveWorker

log = logging.getLogger("locuvi")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; frame-src 'self' blob:; "
        "object-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


class ProfileView:
    """``app.state`` as seen by one request: settings, archive and integrity of its profile."""

    def __init__(self, app_state: Any, profile_id: int) -> None:
        self._app = app_state
        self.profile_id = profile_id
        self.settings = app_state.profile_settings.get(profile_id, app_state.settings)
        self.archive_ctx = app_state.archive_ctxs.get(profile_id)
        self.integrity = app_state.integrities.get(profile_id)
        self.worker = app_state.workers.get(profile_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._app, name)


def open_profile(
    app: FastAPI, settings: Settings, profile_id: int, archive_ctx: ArchiveContext | None
) -> None:
    """Open one profile's database: back up, migrate, check, and start its archive worker."""
    from locuvi.services import backups
    from locuvi.services import invoices as invoice_svc

    st = profiles.settings_for(settings, profile_id)
    st.data_dir.mkdir(parents=True, exist_ok=True)
    st.issued_dir.mkdir(parents=True, exist_ok=True)
    engine = db.init_engine(st.db_path, profile_id)
    with db.use_profile(profile_id):
        backups.before_upgrade(st, engine)  # an update never migrates without a copy
        upgrade(engine)
        with db.new_session() as s:
            core.ensure_singletons(s)
            invoice_svc.refresh_drafts(s)  # drafts follow current rules and rates
            app.state.integrities[profile_id] = integrity.check(s, st)
    app.state.profile_settings[profile_id] = st
    ctx = archive_ctx or ArchiveContext(st, app.state.secrets)
    app.state.archive_ctxs[profile_id] = ctx
    if settings.worker_enabled:
        worker = ArchiveWorker(ctx, profile_id)
        worker.start()
        app.state.workers[profile_id] = worker
        if profile_id == 1:
            app.state.worker = worker


_TITLES = {"dr", "mr", "mrs", "ms", "miss", "mx", "prof", "professor", "sir", "dame"}


def _ensure_admin(settings: Settings) -> None:
    """First start with profiles: the existing owner becomes profile 1, the admin, keeping
    their current password (changed in the app, or the one from the secret file)."""
    if profiles.get(settings, 1) is not None:
        return
    from locuvi.api.auth import hash_password
    from locuvi.models import AuthConfig, OwnerProfile

    with db.use_profile(1), db.new_session() as s:
        cfg = s.get(AuthConfig, 1)
        owner = s.get(OwnerProfile, 1)
        stored = cfg.password_hash if cfg else None
        legal = owner.legal_name if owner else ""
    words = [w for w in (legal or "").replace(".", " ").split() if w.lower() not in _TITLES]
    name = words[0] if words else "Owner"
    if not stored and settings.password:
        stored = hash_password(settings.password)
    profiles.ensure_first(settings, name, stored)


def create_app(
    settings: Settings | None = None, *, archive_ctx: ArchiveContext | None = None
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # Never log request headers (Authorization) from the HTTP client.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ensure_dir_private(settings.key_dir)
        secrets = SecretBox(settings)
        app.state.secrets = secrets
        app.state.profile_settings = {}
        app.state.archive_ctxs = {}
        app.state.integrities = {}
        app.state.workers = {}
        app.state.worker = None
        app.state.digest = None
        app.state.open_profile = lambda pid: open_profile(app, settings, pid, archive_ctx)
        open_profile(app, settings, 1, archive_ctx)
        _ensure_admin(settings)
        for p in profiles.all_profiles(settings):
            if p.id != 1:
                open_profile(app, settings, p.id, None)
        app.state.archive_ctx = app.state.archive_ctxs[1]
        app.state.integrity = app.state.integrities[1]
        app.state.sessions = SessionManager(
            secrets.session_signing_key(),
            mode=settings.auth_mode,
            settings=settings,
            hours=settings.session_hours,
        )
        if settings.worker_enabled:
            app.state.digest = DigestScheduler(settings, secrets)
            app.state.digest.start()
        log.info(
            "Locuvi %s started (auth=%s, env=%s, profiles=%d)", __version__, settings.auth_mode,
            settings.app_env, len(profiles.all_profiles(settings)),
        )  # fmt: skip
        try:
            yield
        finally:
            for worker in app.state.workers.values():
                worker.stop()
            if app.state.digest is not None:
                app.state.digest.stop()
            for pid in list(app.state.profile_settings):
                db.close_profile(pid)

    app = FastAPI(
        title="Locuvi",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )
    app.state.settings = settings

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "request.invalid",
                    "message": "Some fields are not valid.",
                    "params": {"fields": fields},
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            {
                "error": {
                    "code": "server.error",
                    "message": "Something went wrong. Nothing was "
                    "issued unless the invoice now shows a number.",
                    "params": {},
                }
            },
            status_code=500,
        )

    @app.middleware("http")
    async def profile_scope(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Point this request at the signed-in profile's data (profile 1 when signed out)."""
        sm = getattr(app.state, "sessions", None)
        profile = sm.profile_for(request) if sm is not None else None
        pid = profile.id if profile is not None else 1
        request.state.profile = profile
        request.state.view = ProfileView(app.state, pid)
        db.set_profile(pid)
        return await call_next(request)

    @app.middleware("http")
    async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(public)
    app.include_router(api)
    app.include_router(mcp_router)  # Bevro / external agents (token auth, not cookies)
    app.include_router(_inbox.feeds)  # calendar feed by secret link

    static = settings.static_dir
    if static and (static / "index.html").is_file():
        index = static / "index.html"
        if (static / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                return JSONResponse(  # type: ignore[return-value]
                    {"error": {"code": "not_found", "message": "Not found", "params": {}}},
                    status_code=404,
                )
            candidate = (static / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static.resolve()):
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
