"""WebDAV requests from the phone app, where Python runs in the browser (``locuvi.pocket``).

Pyodide has no sockets, so httpx can't connect by itself. This transport hands each request
to ``locuviNet`` in the Web Worker (``frontend/src/pocket/engine.worker.ts``), which waits for
the answer:

- in the Android app, the app makes the connection itself (any Nextcloud, http:// on the
  home network too);
- on iPhone and iPad, the browser makes it, so the Nextcloud must allow Locuvi's address
  (CORS, docs/SYNC.md) and be reached over https://.
"""

from __future__ import annotations

import json

import httpx

# Set by the browser itself; it refuses them from a page. Content-Length follows the body.
_SKIP_REQUEST = {"host", "connection", "content-length", "accept-encoding", "user-agent"}
# The browser has already unpacked the body, so these would describe it wrongly.
_SKIP_RESPONSE = {"content-encoding", "content-length", "transfer-encoding"}


class BrowserTransport(httpx.BaseTransport):
    def __init__(self, net=None) -> None:  # type: ignore[no-untyped-def]
        self._net = net  # tests pass a stand-in for the worker's locuviNet

    def _call(self):  # type: ignore[no-untyped-def]
        if self._net is not None:
            return self._net
        import js  # type: ignore[import-not-found]  # Pyodide only

        return js.locuviNet

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        headers = [
            [k, v] for k, v in request.headers.multi_items() if k.lower() not in _SKIP_REQUEST
        ]
        timeout = request.extensions.get("timeout") or {}
        seconds = max((v for v in timeout.values() if v), default=20.0)
        res = self._call()(
            request.method, str(request.url), json.dumps(headers), body or None, int(seconds * 1000)
        )
        error = _get(res, "error")
        if error == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        if error == "tls":
            raise httpx.ConnectError("SSL certificate verification failed", request=request)
        if error:
            raise httpx.ConnectError(str(error), request=request)
        content = _get(res, "body")
        if content is not None and not isinstance(content, bytes | bytearray):
            content = content.to_bytes()  # a JS Uint8Array
        pairs = json.loads(_get(res, "headers") or "[]")
        return httpx.Response(
            int(_get(res, "status")),
            headers=[(k, v) for k, v in pairs if k.lower() not in _SKIP_RESPONSE],
            content=bytes(content or b""),
            request=request,
        )


def _get(res, key: str):  # type: ignore[no-untyped-def]
    """A field of the worker's answer (a JS object in Pyodide, a dict in tests)."""
    if isinstance(res, dict):
        return res.get(key)
    value = getattr(res, key, None)
    return None if value is None or type(value).__name__ == "JsNull" else value
