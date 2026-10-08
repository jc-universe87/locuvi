"""FastAPI application factory. Serves the API and the built frontend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from locuvi import __version__, db, integrity
from locuvi.api.auth import SessionManager
from locuvi.api.routes import api, public
from locuvi.config import Settings, get_settings
from locuvi.errors import DomainError
from locuvi.migrate import upgrade
from locuvi.secrets_store import SecretBox, ensure_dir_private
from locuvi.services import core
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
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.issued_dir.mkdir(parents=True, exist_ok=True)
        ensure_dir_private(settings.key_dir)
        engine = db.init_engine(settings.db_path)
        upgrade(engine)
        with db.new_session() as s:
            core.ensure_singletons(s)
            app.state.integrity = integrity.check(s, settings)
        secrets = SecretBox(settings)
        app.state.secrets = secrets
        app.state.archive_ctx = archive_ctx or ArchiveContext(settings, secrets)
        app.state.sessions = SessionManager(
            secrets.session_signing_key(),
            mode=settings.auth_mode,
            password=settings.password,
            hours=settings.session_hours,
        )
        app.state.worker = None
        if settings.worker_enabled:
            app.state.worker = ArchiveWorker(app.state.archive_ctx)
            app.state.worker.start()
        log.info(
            "Locuvi %s started (auth=%s, env=%s)", __version__, settings.auth_mode, settings.app_env
        )
        try:
            yield
        finally:
            if app.state.worker is not None:
                app.state.worker.stop()
            engine.dispose()

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
    async def headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(public)
    app.include_router(api)

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
