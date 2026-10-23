"""Where the sync copy lives: a folder, Nextcloud (WebDAV), and later cloud accounts.

Every target stores, under its own "Locuvi Sync" folder:

    state.lcv          the encrypted database copy and file list (replaced on each sync)
    blobs/<name>       each PDF or document, encrypted, written once and never changed

``read_state``/``write_state`` carry a version so a write only lands on the copy that was
read: if another device synced in between, ``write_state`` returns False and the sync starts
again from the newer copy. Nothing written by another device is ever overwritten blindly.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol

STATE = "state.lcv"
FOLDER = "Locuvi Sync"


class TargetError(Exception):
    """The sync folder can't be reached right now (offline, signed out, folder missing)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class Target(Protocol):
    label: str

    def read_state(self) -> tuple[bytes, str] | None: ...
    def write_state(self, data: bytes, version: str | None) -> bool: ...
    def blob_names(self) -> set[str]: ...
    def read_blob(self, name: str) -> bytes: ...
    def write_blob(self, name: str, data: bytes) -> None: ...


def _check_name(name: str) -> str:
    if not name or not all(c in "0123456789abcdef" for c in name) or len(name) > 128:
        raise TargetError("sync.bad_name", "Unexpected file name in the sync folder.")
    return name


class FolderTarget:
    """A folder on this computer, typically one that Google Drive, OneDrive, Dropbox or
    iCloud Drive keeps in step with their cloud."""

    def __init__(self, folder: Path) -> None:
        self.root = Path(folder) / FOLDER
        self.label = str(folder)

    def _ready(self) -> None:
        if not self.root.parent.is_dir():
            raise TargetError("sync.folder_missing", "The sync folder can't be found.")
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)

    def read_state(self) -> tuple[bytes, str] | None:
        self._ready()
        f = self.root / STATE
        if not f.is_file():
            return None
        data = f.read_bytes()
        return data, hashlib.sha256(data).hexdigest()

    def write_state(self, data: bytes, version: str | None) -> bool:
        self._ready()
        current = self.read_state()
        if (current[1] if current else None) != version:
            return False
        tmp = self.root / f".{STATE}.{os.getpid()}.part"
        tmp.write_bytes(data)
        os.replace(tmp, self.root / STATE)
        return True

    def blob_names(self) -> set[str]:
        self._ready()
        return {p.name for p in (self.root / "blobs").iterdir() if not p.name.startswith(".")}

    def read_blob(self, name: str) -> bytes:
        return (self.root / "blobs" / _check_name(name)).read_bytes()

    def write_blob(self, name: str, data: bytes) -> None:
        self._ready()
        dest = self.root / "blobs" / _check_name(name)
        if dest.exists():
            return
        tmp = dest.with_name(f".{name}.part")
        tmp.write_bytes(data)
        os.replace(tmp, dest)


class WebDavTarget:
    """Nextcloud (or any WebDAV server), using Locuvi's existing Nextcloud connection."""

    def __init__(self, client, base_path: list[str], label: str) -> None:  # type: ignore[no-untyped-def]
        from locuvi.webdav.urlguard import encode_path

        self.client = client
        self.label = label
        self._root = encode_path([*base_path, FOLDER])
        self._encode = encode_path
        self._base_path = base_path

    def _rel(self, *parts: str) -> str:
        return self._encode([*self._base_path, FOLDER, *parts])

    def _call(self, fn, *a):  # type: ignore[no-untyped-def]
        from locuvi.webdav.client import WebDavError

        try:
            return fn(*a)
        except WebDavError as exc:
            code = f"sync.webdav_{exc.error_class}"
            raise TargetError(code, "Nextcloud can't be reached.") from None

    def _ready(self) -> None:
        segs = [*self._base_path, FOLDER, "blobs"]
        for i in range(1, len(segs) + 1):
            self._call(self.client.mkcol, self._encode(segs[:i]))

    def read_state(self) -> tuple[bytes, str] | None:
        got = self._call(self.client.get, self._rel(STATE))
        if got is None:
            return None
        data, etag = got
        return data, etag or hashlib.sha256(data).hexdigest()

    def write_state(self, data: bytes, version: str | None) -> bool:
        self._ready()
        return bool(self._call(self.client.put_if, self._rel(STATE), data, version))

    def blob_names(self) -> set[str]:
        self._ready()
        return set(self._call(self.client.list_names, self._rel("blobs")))

    def read_blob(self, name: str) -> bytes:
        got = self._call(self.client.get, self._rel("blobs", _check_name(name)))
        if got is None:
            raise TargetError("sync.blob_missing", "A file is missing from the sync folder.")
        return got[0]

    def write_blob(self, name: str, data: bytes) -> None:
        self._call(self.client.put_if, self._rel("blobs", _check_name(name)), data, None)
