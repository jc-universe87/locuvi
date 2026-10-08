"""SSRF protection for user-entered WebDAV endpoints.

Default policy: HTTPS only, public addresses only. Deliberately private targets
(Tailscale/LAN Nextcloud) must be allowlisted by the administrator via
``WEBDAV_ALLOWED_PRIVATE_HOSTS``; protections are never disabled globally.
"""

from __future__ import annotations

import ipaddress
import socket
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from locuvi.config import Settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UrlBlocked(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedUrl:
    url: str  # normalised, always ends with "/"
    scheme: str
    host: str
    port: int | None
    allowlisted: bool


_METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


def _ip_is_public(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in ipaddress.ip_network("100.64.0.0/10")  # CGNAT / Tailscale
    )


def validate_base_url(raw: str, settings: Settings) -> ValidatedUrl:
    raw = (raw or "").strip()
    if not raw or len(raw) > 500:
        raise UrlBlocked("invalid", "Enter the full WebDAV URL.")
    if any(c.isspace() or ord(c) < 32 for c in raw):
        raise UrlBlocked("invalid", "The WebDAV URL contains spaces or control characters.")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"https", "http"}:
        raise UrlBlocked("scheme", "Only https:// WebDAV URLs are allowed.")
    if parts.username or parts.password:
        raise UrlBlocked("userinfo", "Do not put credentials in the URL.")
    if parts.query or parts.fragment:
        raise UrlBlocked("invalid", "The WebDAV URL must not contain ? or #.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlBlocked("invalid", "The WebDAV URL has no host name.")
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlBlocked("invalid", "The WebDAV URL has an invalid port.") from exc

    allow = settings.webdav_allowlist
    literal: IPAddress | None
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    allowlisted = allow.allows_host(host) or (literal is not None and allow.allows_ip(literal))

    if scheme == "http" and not (allowlisted and settings.webdav_allow_http_for_allowlisted):
        raise UrlBlocked("scheme", "Only https:// WebDAV URLs are allowed.")
    if not allowlisted:
        if host == "localhost" or host.endswith(".localhost") or host in _METADATA_HOSTS:
            raise UrlBlocked("private", "Local and internal addresses are blocked.")
        if literal is not None and not _ip_is_public(literal):
            raise UrlBlocked(
                "private",
                "Private, loopback and link-local addresses are blocked unless the "
                "administrator allowlists them.",
            )

    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    # Re-encode the path conservatively without double-encoding existing escapes.
    path = quote(path, safe="/%@:+~-._!$&'()*,;=")
    netloc = parts.netloc.lower() if not literal else parts.netloc
    return ValidatedUrl(f"{scheme}://{netloc}{path}", scheme, host, port, allowlisted)


def resolve_and_check(host: str, port: int | None, settings: Settings) -> None:
    """Resolve at request time and reject non-public addresses (unless allowlisted)."""
    host = host.lower().rstrip(".")
    allow = settings.webdav_allowlist
    if allow.allows_host(host):
        return
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlBlocked("dns", "The WebDAV host name could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if allow.allows_ip(ip):
            continue
        if not _ip_is_public(ip):
            raise UrlBlocked(
                "private",
                "The WebDAV host resolves to a private or internal address. Ask the "
                "administrator to allowlist it if this is intended.",
            )


# ----------------------------------------------------------------------- paths

MAX_SEGMENT = 100
_FORBIDDEN = set('/\\:*?"<>|')


class InvalidPath(ValueError):
    pass


def validate_segment(seg: str) -> str:
    seg = unicodedata.normalize("NFC", seg.strip())
    if not seg or seg in {".", ".."}:
        raise InvalidPath("Folder names cannot be empty, '.' or '..'.")
    if len(seg) > MAX_SEGMENT:
        raise InvalidPath("Folder names must be at most 100 characters.")
    if any(c in _FORBIDDEN or unicodedata.category(c).startswith("C") for c in seg):
        raise InvalidPath('Folder names cannot contain / \\ : * ? " < > | or control characters.')
    if seg.startswith(".") or seg.endswith(" ") or seg.endswith("."):
        raise InvalidPath("Folder names cannot start with '.' or end with a space or '.'.")
    return seg


def validate_base_path(raw: str) -> list[str]:
    segments = [s for s in (raw or "").replace("\\", "/").split("/") if s.strip()]
    if len(segments) > 10:
        raise InvalidPath("Use at most 10 folder levels.")
    return [validate_segment(s) for s in segments]


def encode_path(segments: list[str]) -> str:
    return "/".join(quote(s, safe="") for s in segments)
