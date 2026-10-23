"""Locuvi inside the phone app: the whole backend in Pyodide (Python in the browser).

The Android app and the iPhone/iPad Home Screen app load Pyodide in a Web Worker
(``frontend/src/pocket/engine.worker.ts``), then call ``start`` once and ``handle`` for each
request the web app makes, instead of sending it over the network. Records are kept on the
phone and copied to its storage after every change; sync (``locuvi.sync``) keeps them in step
with the owner's other devices.

A browser can't open network connections of its own, and Pyodide has no threads, so:

- work that FastAPI would hand to a thread runs straight away (one request at a time);
- there are no background workers: the app's own timer asks for a sync now and then;
- reading email (IMAP) and sending it (SMTP) happen on a computer; the phone shares PDFs.
"""

from __future__ import annotations

import json
import os
from typing import Any

_app: Any = None
_lifespan: Any = None


async def start(root: str) -> dict[str, Any]:
    """Open Locuvi with its records under ``root`` (a folder kept in the phone's storage)."""
    global _app, _lifespan
    if _app is not None:
        return {"ok": True}
    import anyio.to_thread

    async def run_now(func, *args, abandon_on_cancel=False, cancellable=None, limiter=None):  # type: ignore[no-untyped-def]
        return func(*args)

    anyio.to_thread.run_sync = run_now  # no threads in Pyodide
    os.environ.update(
        APP_ENV="production",
        DATA_DIR=f"{root}/data",
        KEY_DIR=f"{root}/keys",
        LOCUVI_AUTH_MODE="gateway",  # the phone's own lock protects it, like any app
        COOKIE_SECURE="false",
        ARCHIVE_WORKER_ENABLED="false",
        LOCUVI_POCKET="1",
    )
    import logging

    logging.getLogger("alembic").setLevel(logging.WARNING)
    from locuvi.config import Settings
    from locuvi.main import create_app

    app = create_app(Settings.from_env())
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    _app, _lifespan = app, lifespan
    return {"ok": True}


async def handle(method: str, url: str, headers_json: str, body: bytes | None) -> dict[str, Any]:
    """One request from the web app. Returns status, headers and body (bytes)."""
    from urllib.parse import unquote

    raw_path, _, query = url.partition("?")
    path = unquote(raw_path)  # ASGI: "path" is decoded, "raw_path" is as sent
    headers = [(k.lower().encode("latin-1"), v.encode("latin-1"))
               for k, v in json.loads(headers_json or "{}").items()]  # fmt: skip
    headers.append((b"host", b"locuvi.pocket"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "https",
        "path": path,
        "raw_path": raw_path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": headers,
        "server": ("locuvi.pocket", 443),
        "client": ("127.0.0.1", 0),
        "state": {},
    }
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": bytes(body or b""), "more_body": False}

    out: dict[str, Any] = {"status": 500, "headers": [], "body": b""}
    chunks: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = [(k.decode("latin-1"), v.decode("latin-1"))
                              for k, v in message.get("headers", [])]  # fmt: skip
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await _app(scope, receive, send)
    out["body"] = b"".join(chunks)
    return out


async def handle_js(method: str, url: str, headers_json: str, body: Any) -> dict[str, Any]:
    """``handle`` for the Web Worker: takes a JS Uint8Array (or null). The worker converts
    the result with ``toJs`` (the body bytes become a Uint8Array)."""
    raw = body.to_bytes() if body is not None and hasattr(body, "to_bytes") else body
    out = await handle(method, url, headers_json, raw)
    out["headers"] = [list(h) for h in out["headers"]]
    return out
