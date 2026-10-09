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
from typing import Any

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
    """Signed session cookies naming the profile they belong to.

    A token is ``v3.<profile>.<expiry>.<epoch>.<nonce>.<sig>``. The epoch is the profile's
    session epoch: changing or resetting its password (or removing the profile) bumps it, so
    every older session of that profile stops working. Tokens from before profiles existed
    (v1/v2) belong to profile 1.
    """

    def __init__(self, key: bytes, *, mode: str, settings: Any, hours: int) -> None:
        self._key = key
        self.mode = mode
        self._settings = settings
        self._ttl = hours * 3600
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    # -- profiles

    def _profiles(self) -> list[Any]:
        from locuvi import profiles

        return profiles.all_profiles(self._settings)

    def login_required(self) -> bool:
        """Gateway mode with a single profile needs no in-app sign-in; anything else does."""
        return self.mode == "password" or len(self._profiles()) > 1

    def multi(self) -> bool:
        return len(self._profiles()) > 1

    # -- tokens

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def issue_token(self, profile: Any) -> str:
        expiry = int(time.time()) + self._ttl
        nonce = _b64(secrets.token_bytes(16))
        payload = f"v3.{profile.id}.{expiry}.{profile.session_epoch}.{nonce}"
        return f"{payload}.{self._sign(payload)}"

    def profile_for_token(self, token: str | None) -> Any:
        """The active profile a valid token belongs to, or None."""
        from locuvi import profiles

        if not token or token.count(".") not in (3, 4, 5):
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        parts = payload.split(".")
        try:
            if parts[0] == "v3" and len(parts) == 5:
                pid, expiry, epoch = int(parts[1]), int(parts[2]), int(parts[3])
            elif parts[0] == "v2" and len(parts) == 4:
                pid, expiry, epoch = 1, int(parts[1]), int(parts[2])
            elif parts[0] == "v1":
                pid, expiry, epoch = 1, int(parts[1]), 0
            else:
                return None
        except ValueError:
            return None
        if expiry <= time.time():
            return None
        profile = profiles.active(self._settings, pid)
        if profile is None or profile.session_epoch != epoch:
            return None
        return profile

    def csrf_for(self, token: str | None) -> str:
        basis = token if self.login_required() else "gateway-mode"
        return self._sign(f"csrf:{basis}")

    def check_password(self, name: str | None, attempt: str) -> Any:
        """The profile whose name and password match, or None. Rate limited."""
        from locuvi import profiles

        now = time.monotonic()
        with self._lock:  # reserve this attempt before the (slow) check: bursts can't bypass
            while self._failures and now - self._failures[0] > 300:
                self._failures.popleft()
            if len(self._failures) >= 5:
                raise TooManyAttempts(
                    "auth.too_many_attempts", "Too many attempts. Wait a few minutes."
                )
            self._failures.append(now)
        if name and name.strip():
            profile = profiles.by_name(self._settings, name)
        else:  # one profile (or an old sign-in screen): the admin
            active = profiles.all_profiles(self._settings)
            profile = active[0] if len(active) == 1 else None
        stored = profile.password_hash if profile else None
        ok = bool(stored and verify_password(attempt, stored))
        if ok:
            with self._lock:  # a correct password doesn't count against the limit
                try:
                    self._failures.remove(now)
                except ValueError:
                    pass
            return profile
        return None

    def profile_for(self, request: Request) -> Any:
        """The signed-in profile of a request (gateway mode with one profile: the admin)."""
        from locuvi import profiles

        if not self.login_required():
            return profiles.active(self._settings, 1)
        return self.profile_for_token(request.cookies.get(COOKIE))

    def authenticated(self, request: Request) -> bool:
        return self.profile_for(request) is not None

    def enforce(self, request: Request) -> None:
        profile = getattr(request.state, "profile", None) or self.profile_for(request)
        if profile is None:
            raise Unauthorized("auth.required", "Please sign in.")
        if request.method not in SAFE_METHODS:
            expected = self.csrf_for(request.cookies.get(COOKIE))
            got = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(got, expected):
                raise Forbidden("auth.csrf", "Security check failed. Reload the page.")
