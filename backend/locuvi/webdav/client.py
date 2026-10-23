"""Minimal server-side WebDAV client (PROPFIND/MKCOL/PUT/MOVE/GET/DELETE).

- HTTP Basic auth with a dedicated app password; TLS verification always on.
- Redirects are never followed (credentials must not cross hosts).
- Every request re-checks the resolved address against the SSRF policy.
- Authorization headers and passwords are never logged or put in errors.
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

from locuvi.config import Settings
from locuvi.webdav.urlguard import UrlBlocked, ValidatedUrl, resolve_and_check

MAX_DOWNLOAD = 50 * 1024 * 1024
DAV_NS = "{DAV:}"


class WebDavError(Exception):
    """error_class is a stable, non-secret identifier shown to the user."""

    def __init__(self, error_class: str, detail: str = "", retry_after: float | None = None):
        super().__init__(f"{error_class}: {detail}" if detail else error_class)
        self.error_class = error_class
        self.detail = detail
        self.retry_after = retry_after


PAUSING_ERRORS = {
    "auth_rejected",
    "permission_denied",
    "url_blocked",
    "redirect_blocked",
    "credentials_unavailable",
    "base_not_found",
    "not_configured",
}


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            from datetime import UTC, datetime

            return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError):
            return None


def classify_status(resp: httpx.Response, context: str) -> WebDavError:
    code = resp.status_code
    if code == 401:
        return WebDavError("auth_rejected", f"{context}: authentication rejected")
    if code == 403:
        return WebDavError("permission_denied", f"{context}: permission denied")
    if code == 429:
        return WebDavError("rate_limited", context, _retry_after(resp))
    if code == 507:
        return WebDavError("insufficient_storage", context)
    if 300 <= code < 400:
        return WebDavError("redirect_blocked", f"{context}: server redirected (HTTP {code})")
    if code == 503:
        return WebDavError("server_unavailable", context, _retry_after(resp))
    if code >= 500:
        return WebDavError("server_error", f"{context}: HTTP {code}")
    return WebDavError("protocol_error", f"{context}: unexpected HTTP {code}")


@dataclass
class RemoteState:
    exists: bool
    is_collection: bool = False
    etag: str | None = None
    size: int | None = None


class WebDavClient:
    def __init__(
        self,
        base: ValidatedUrl,
        username: str,
        password: str,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        check_dns: bool = True,
    ) -> None:
        self.base = base
        self._settings = settings
        self._check_dns = check_dns
        if transport is None and os.environ.get("LOCUVI_POCKET") == "1":
            from locuvi.webdav.browser import BrowserTransport

            # the phone app: the app or browser connects, and does its own name lookup
            transport, self._check_dns = BrowserTransport(), False
        hooks = {"request": [self._guard]}
        self._http = httpx.Client(
            auth=httpx.BasicAuth(username, password),
            timeout=httpx.Timeout(settings.webdav_timeout_seconds),
            follow_redirects=False,
            verify=True,
            transport=transport,
            event_hooks=hooks,
            headers={"User-Agent": "Locuvi/0.1 (+WebDAV archive)"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WebDavClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _guard(self, request: httpx.Request) -> None:
        if request.url.host.lower().rstrip(".") != self.base.host:
            raise UrlBlocked("host_changed", "request host differs from configured host")
        if self._check_dns and not self.base.allowlisted:
            resolve_and_check(
                request.url.host, request.url.port, self._settings, home=self.base.home
            )

    def url(self, encoded_rel: str) -> str:
        return self.base.url + encoded_rel.lstrip("/")

    def _send(self, method: str, encoded_rel: str, **kw) -> httpx.Response:  # type: ignore[no-untyped-def]
        try:
            return self._http.request(method, self.url(encoded_rel), **kw)
        except UrlBlocked as exc:
            raise WebDavError("url_blocked", str(exc)) from None
        except httpx.TimeoutException:
            raise WebDavError("timeout", f"{method} timed out") from None
        except httpx.ConnectError as exc:
            if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
                raise WebDavError("tls_error", "TLS certificate verification failed") from None
            raise WebDavError("unreachable", "could not connect to the server") from None
        except httpx.TransportError:
            raise WebDavError("network_error", f"{method} failed in transit") from None

    # ------------------------------------------------------------------ methods

    def stat(self, encoded_rel: str) -> RemoteState:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getetag/>'
            "<d:getcontentlength/></d:prop></d:propfind>"
        )
        resp = self._send(
            "PROPFIND",
            encoded_rel,
            headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
            content=body.encode(),
        )
        if resp.status_code == 404:
            return RemoteState(exists=False)
        if resp.status_code != 207:
            raise classify_status(resp, "PROPFIND")
        return _parse_propfind(resp.content)

    def reachable(self, timeout: float = 6.0) -> bool:
        """Whether the server answers at all, quickly (choosing between two addresses).

        Any HTTP answer counts, even a refusal: the real request then reports what's wrong."""
        try:
            self._http.request("OPTIONS", self.base.url, timeout=timeout)
        except (UrlBlocked, httpx.TransportError):
            return False
        return True

    def mkcol(self, encoded_rel: str) -> str:
        """Returns 'created' or 'exists'."""
        resp = self._send("MKCOL", encoded_rel.rstrip("/") + "/")
        if resp.status_code == 201:
            return "created"
        if resp.status_code == 405:
            return "exists"  # MKCOL on an existing resource
        if resp.status_code == 409:
            raise WebDavError("base_not_found", "parent folder does not exist")
        raise classify_status(resp, "MKCOL")

    def put(self, encoded_rel: str, data: bytes, content_type: str = "application/pdf") -> None:
        resp = self._send("PUT", encoded_rel, content=data, headers={"Content-Type": content_type})
        if resp.status_code in (200, 201, 204):
            return
        if resp.status_code == 409:
            raise WebDavError("base_not_found", "target folder does not exist")
        raise classify_status(resp, "PUT")

    def move_no_overwrite(self, src_rel: str, dst_rel: str) -> bool:
        """MOVE with Overwrite: F. Returns False when the destination already exists."""
        resp = self._send(
            "MOVE", src_rel, headers={"Destination": self.url(dst_rel), "Overwrite": "F"}
        )
        if resp.status_code in (201, 204):
            return True
        if resp.status_code == 412:
            return False
        raise classify_status(resp, "MOVE")

    def get_sha256(self, encoded_rel: str, max_bytes: int = MAX_DOWNLOAD) -> str | None:
        """SHA-256 of the remote file, or None if it does not exist."""
        try:
            with self._http.stream("GET", self.url(encoded_rel)) as resp:
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    raise classify_status(resp, "GET")
                h = hashlib.sha256()
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return "too-large"
                    h.update(chunk)
                return h.hexdigest()
        except UrlBlocked as exc:
            raise WebDavError("url_blocked", str(exc)) from None
        except httpx.TimeoutException:
            raise WebDavError("timeout", "GET timed out") from None
        except httpx.ConnectError:
            raise WebDavError("unreachable", "could not connect to the server") from None
        except httpx.TransportError:
            raise WebDavError("network_error", "GET failed in transit") from None

    def get(self, encoded_rel: str, max_bytes: int = MAX_DOWNLOAD) -> tuple[bytes, str] | None:
        """The file and its ETag, or None if it does not exist (sync)."""
        resp = self._send("GET", encoded_rel)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise classify_status(resp, "GET")
        if len(resp.content) > max_bytes:
            raise WebDavError("too_large", "remote file is too large")
        etag = resp.headers.get("ETag", "")
        if not etag:
            # A browser hides ETag unless the server lists it (CORS Expose-Headers). Ask for it
            # in a listing, then read the file again: if it changed in between, the version is
            # the older one, so the next put_if is refused and nothing is overwritten.
            st = self.stat(encoded_rel)
            if not st.exists or not st.etag:
                return resp.content, ""
            again = self._send("GET", encoded_rel)
            if again.status_code != 200:
                raise classify_status(again, "GET")
            return again.content, f'"{st.etag}"'
        return resp.content, etag

    def put_if(self, encoded_rel: str, data: bytes, etag: str | None) -> bool:
        """PUT only if the file is still the version read (``etag``), or still absent (None).

        Returns False when another device changed it first (412), so nothing is overwritten.
        """
        headers = {"Content-Type": "application/octet-stream"}
        if etag:
            headers["If-Match"] = etag
        else:
            headers["If-None-Match"] = "*"
        resp = self._send("PUT", encoded_rel, content=data, headers=headers)
        if resp.status_code in (200, 201, 204):
            return True
        if resp.status_code == 412:
            return False
        if resp.status_code == 409:
            raise WebDavError("base_not_found", "target folder does not exist")
        raise classify_status(resp, "PUT")

    def list_names(self, encoded_rel: str) -> list[str]:
        """Names of the files directly inside a folder (PROPFIND, Depth 1)."""
        resp = self._send(
            "PROPFIND",
            encoded_rel.rstrip("/") + "/",
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            content=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
            b"<d:resourcetype/></d:prop></d:propfind>",
        )
        if resp.status_code == 404:
            return []
        if resp.status_code != 207:
            raise classify_status(resp, "PROPFIND")
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise WebDavError("protocol_error", "invalid PROPFIND response") from exc
        from urllib.parse import unquote

        names = []
        for r in root.iter(f"{DAV_NS}response"):
            href = (r.findtext(f"{DAV_NS}href") or "").rstrip("/")
            name = unquote(href.rsplit("/", 1)[-1])
            if r.find(f".//{DAV_NS}collection") is None and name:
                names.append(name)
        return names

    def delete_quietly(self, encoded_rel: str) -> None:
        try:
            self._send("DELETE", encoded_rel)
        except WebDavError:
            pass


def _parse_propfind(content: bytes) -> RemoteState:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise WebDavError("protocol_error", "invalid PROPFIND response") from exc
    for resp in root.iter(f"{DAV_NS}response"):
        for propstat in resp.iter(f"{DAV_NS}propstat"):
            status = propstat.findtext(f"{DAV_NS}status") or ""
            if " 200 " not in f" {status} " and "200" not in status:
                continue
            prop = propstat.find(f"{DAV_NS}prop")
            if prop is None:
                continue
            rtype = prop.find(f"{DAV_NS}resourcetype")
            is_col = rtype is not None and rtype.find(f"{DAV_NS}collection") is not None
            etag = prop.findtext(f"{DAV_NS}getetag")
            size_txt = prop.findtext(f"{DAV_NS}getcontentlength")
            size = int(size_txt) if size_txt and size_txt.isdigit() else None
            return RemoteState(True, is_col, etag.strip('"') if etag else None, size)
        return RemoteState(True)
    return RemoteState(True)
