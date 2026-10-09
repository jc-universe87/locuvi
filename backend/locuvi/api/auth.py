"""Authentication boundary (docs/decisions/0002-auth-model.md).

Modes:
- ``password``: single owner password from a secret file; signed, HttpOnly,
  SameSite=Strict session cookie.
- ``gateway``: no in-app login; the deployment MUST sit behind an
  authenticated private gateway (e.g. Tailscale). Chosen explicitly.

In both modes every state-changing request needs an ``X-CSRF-Token`` header
bound to the session. Cross-origin pages cannot read or set it (no CORS).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

from fastapi import Request

from locuvi.errors import DomainError

COOKIE = "locuvi_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class Unauthorized(DomainError):
    status_code = 401


class Forbidden(DomainError):
    status_code = 403


class TooManyAttempts(DomainError):
    status_code = 429


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        salt = base64.urlsafe_b64decode(pad(salt_b64))
        want = base64.urlsafe_b64decode(pad(dk_b64))
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=len(want),
                             n=int(n), r=int(r), p=int(p))  # fmt: skip
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, want)


class SessionManager:
    def __init__(
        self,
        key: bytes,
        *,
        mode: str,
        password: str | None,
        hours: int,
        password_hash: str | None = None,
        epoch: int = 0,
    ) -> None:
        self._key = key
        self.mode = mode
        self._password = password
        self._hash = password_hash
        self._epoch = epoch
        self._ttl = hours * 3600
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    def set_password_hash(self, password_hash: str | None, epoch: int) -> None:
        """Called after an in-app password change (or reset): old sessions stop working."""
        with self._lock:
            self._hash, self._epoch = password_hash, epoch

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def issue_token(self) -> str:
        expiry = int(time.time()) + self._ttl
        payload = f"v2.{expiry}.{self._epoch}.{_b64(secrets.token_bytes(16))}"
        return f"{payload}.{self._sign(payload)}"

    def valid_token(self, token: str | None) -> bool:
        if not token or token.count(".") not in (3, 4):
            return False
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return False
        parts = payload.split(".")
        try:
            expiry = int(parts[1])
            # v1 tokens (before epochs existed) count as epoch 0
            epoch = int(parts[2]) if parts[0] == "v2" and len(parts) == 4 else 0
        except ValueError:
            return False
        if parts[0] not in ("v1", "v2") or epoch != self._epoch:
            return False
        return expiry > time.time()

    def csrf_for(self, token: str | None) -> str:
        basis = token if self.mode == "password" else "gateway-mode"
        return self._sign(f"csrf:{basis}")

    def check_password(self, attempt: str) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._failures and now - self._failures[0] > 300:
                self._failures.popleft()
            if len(self._failures) >= 5:
                raise TooManyAttempts(
                    "auth.too_many_attempts", "Too many attempts. Wait a few minutes."
                )
            if self._hash:
                ok = verify_password(attempt, self._hash)
            else:
                ok = self._password is not None and hmac.compare_digest(
                    attempt.encode("utf-8"), self._password.encode("utf-8")
                )
            if not ok:
                self._failures.append(now)
            return ok

    def authenticated(self, request: Request) -> bool:
        if self.mode == "gateway":
            return True
        return self.valid_token(request.cookies.get(COOKIE))

    def enforce(self, request: Request) -> None:
        if not self.authenticated(request):
            raise Unauthorized("auth.required", "Please sign in.")
        if request.method not in SAFE_METHODS:
            expected = self.csrf_for(request.cookies.get(COOKIE))
            got = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(got, expected):
                raise Forbidden("auth.csrf", "Security check failed. Reload the page.")
