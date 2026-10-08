"""Runtime configuration, read from environment variables.

Secrets are never read from tracked config files: they come from mounted
secret files (``*_FILE`` variables) or are generated into the key directory.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_secret_file(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    value = p.read_text(encoding="utf-8").strip()
    return value or None


@dataclass(frozen=True)
class WebDavAllowlist:
    """Administrator allowlist for deliberately private WebDAV targets.

    Entries are hostnames (exact, case-insensitive) or IP networks in CIDR
    notation, e.g. ``nextcloud.tailnet.ts.net,100.64.0.0/10``.
    """

    hosts: frozenset[str] = frozenset()
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    @classmethod
    def parse(cls, raw: str | None) -> WebDavAllowlist:
        hosts: set[str] = set()
        nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for item in (raw or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                hosts.add(item.lower().rstrip("."))
        return cls(frozenset(hosts), tuple(nets))

    def allows_host(self, host: str) -> bool:
        return host.lower().rstrip(".") in self.hosts

    def allows_ip(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return any(ip in net for net in self.networks)


@dataclass(frozen=True)
class Settings:
    app_env: str = "production"
    data_dir: Path = Path("/data")
    key_dir: Path = Path("/keys")
    static_dir: Path | None = None
    auth_mode: str = "password"  # "password" | "gateway"
    password: str | None = None
    cookie_secure: bool = True
    session_hours: int = 12
    webdav_allowlist: WebDavAllowlist = field(default_factory=WebDavAllowlist)
    webdav_allow_http_for_allowlisted: bool = False
    webdav_timeout_seconds: float = 20.0
    webdav_password_override: str | None = None
    encryption_key_file: Path | None = None
    worker_enabled: bool = True
    worker_poll_seconds: float = 15.0
    backup_dir: Path | None = None  # automatic nightly backups go here (BACKUP_DIR)
    backup_keep_days: int = 30
    log_level: str = "INFO"

    @property
    def debug(self) -> bool:
        return self.app_env == "development"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "locuvi.db"

    @property
    def issued_dir(self) -> Path:
        return self.data_dir / "invoices" / "issued"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "invoices" / "quarantine"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ if env is None else env)
        app_env = e.get("APP_ENV", "production")
        static = e.get("STATIC_DIR")
        key_file = e.get("ENCRYPTION_KEY_FILE")
        password = _read_secret_file(e.get("LOCUVI_PASSWORD_FILE")) or e.get("LOCUVI_PASSWORD")
        return cls(
            app_env=app_env,
            data_dir=Path(e.get("DATA_DIR", "/data")),
            key_dir=Path(e.get("KEY_DIR", "/keys")),
            static_dir=Path(static) if static else None,
            auth_mode=e.get("LOCUVI_AUTH_MODE", "password").strip().lower(),
            password=password or None,
            cookie_secure=_bool(e.get("COOKIE_SECURE"), default=app_env != "development"),
            session_hours=int(e.get("SESSION_HOURS", "12")),
            webdav_allowlist=WebDavAllowlist.parse(e.get("WEBDAV_ALLOWED_PRIVATE_HOSTS")),
            webdav_allow_http_for_allowlisted=_bool(e.get("WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED")),
            webdav_timeout_seconds=float(e.get("WEBDAV_TIMEOUT_SECONDS", "20")),
            webdav_password_override=_read_secret_file(e.get("WEBDAV_SECRET_FILE")),
            encryption_key_file=Path(key_file) if key_file else None,
            worker_enabled=_bool(e.get("ARCHIVE_WORKER_ENABLED"), default=True),
            worker_poll_seconds=float(e.get("ARCHIVE_WORKER_POLL_SECONDS", "15")),
            log_level=e.get("LOG_LEVEL", "INFO").upper(),
            backup_dir=Path(e["BACKUP_DIR"]) if e.get("BACKUP_DIR") else None,
            backup_keep_days=int(e.get("BACKUP_KEEP_DAYS", "30")),
        )

    def validate(self) -> None:
        if self.auth_mode not in {"password", "gateway"}:
            raise RuntimeError("LOCUVI_AUTH_MODE must be 'password' or 'gateway'")
        if self.auth_mode == "password" and not self.password:
            raise RuntimeError(
                "LOCUVI_AUTH_MODE=password requires LOCUVI_PASSWORD_FILE (recommended) "
                "or LOCUVI_PASSWORD. Use LOCUVI_AUTH_MODE=gateway only behind an "
                "authenticated private gateway such as Tailscale."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
