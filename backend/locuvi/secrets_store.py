"""Server-held key management and at-rest encryption of UI-entered secrets.

The encryption key lives outside the database: either a mounted secret file
(``ENCRYPTION_KEY_FILE``) or a key generated once into ``KEY_DIR`` (a separate
volume from ``/data`` so that a copy of the data volume alone does not reveal
the WebDAV app password).
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from locuvi.config import Settings


class SecretUnavailable(RuntimeError):
    pass


def _load_or_create_key(settings: Settings) -> bytes:
    if settings.encryption_key_file is not None:
        try:
            raw = settings.encryption_key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SecretUnavailable("encryption key file is not readable") from exc
        if not raw:
            raise SecretUnavailable("encryption key file is empty")
        # Accept any high-entropy string; derive a Fernet key from it.
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())

    path = settings.key_dir / "locuvi.key"
    if path.is_file():
        return path.read_bytes().strip()
    settings.key_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return key


class SecretBox:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._key: bytes | None = None
        self._fernet: Fernet | None = None

    def _f(self) -> Fernet:
        if self._fernet is None:
            self._key = _load_or_create_key(self._settings)
            self._fernet = Fernet(self._key)
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        return self._f().encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._f().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretUnavailable(
                "stored credential cannot be decrypted with the current key"
            ) from exc

    def session_signing_key(self) -> bytes:
        """Key for signing session cookies, derived from the server key."""
        self._f()
        assert self._key is not None
        return hashlib.sha256(b"locuvi-session-v1:" + self._key).digest()


def ensure_dir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
