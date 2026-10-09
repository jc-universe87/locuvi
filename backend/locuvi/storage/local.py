"""Crash-safe local storage for issued invoice PDFs."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    sha256: str
    size: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_issued_pdf(
    data_dir: Path, invoice_id: str, data: bytes, folder: str = "issued"
) -> StoredFile:
    """Write ``invoices/{folder}/{invoice_id}.pdf`` via temp file, fsync and rename.

    Refuses to replace an existing file with *different* content: an issued
    artifact is never silently overwritten.
    """
    uuid.UUID(invoice_id)  # path-safety: only UUID basenames
    if folder not in {"issued", "credit"}:
        raise ValueError("unknown PDF folder")
    rel = f"invoices/{folder}/{invoice_id}.pdf"
    target = data_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(data)
    if target.exists():
        if sha256_file(target) == digest:
            return StoredFile(rel, digest, len(data))
        # Left over from an issue attempt that never committed: quarantine it.
        quarantine = data_dir / "invoices" / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        os.replace(target, quarantine / f"{invoice_id}.{uuid.uuid4().hex[:8]}.pdf")
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(target.parent)
    return StoredFile(rel, digest, len(data))


def resolve(data_dir: Path, relative_path: str) -> Path:
    path = (data_dir / relative_path).resolve()
    if not path.is_relative_to(data_dir.resolve()):
        raise ValueError("path escapes data directory")
    return path
