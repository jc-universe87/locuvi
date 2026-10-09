"""Passphrase encryption for backups that leave the server.

Format (all integers big-endian):
  MAGIC(8) | salt(16) | log2_n(1) | r(1) | p(1) | nonce_prefix(7) | chunks...
  chunk = length(4) | AES-256-GCM ciphertext+tag
The key comes from scrypt(passphrase, salt). Each chunk's nonce is the prefix plus a 4-byte
counter, and its associated data binds the header, the chunk index and a "last chunk" flag, so
reordering, truncation and tampering are all detected. The passphrase is never stored.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"LOCUVI\x01E"
CHUNK = 1024 * 1024
LOG2_N, R, P = 15, 8, 1
HEADER_LEN = len(MAGIC) + 16 + 3 + 7
MIN_PASSPHRASE = 12


class DecryptError(Exception):
    """Wrong passphrase, or the file is damaged or not a Locuvi encrypted backup."""


def _key(passphrase: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    if not 14 <= log2_n <= 20 or not 1 <= r <= 16 or not 1 <= p <= 4:
        raise DecryptError("unsupported key parameters")
    return Scrypt(salt=salt, length=32, n=2**log2_n, r=r, p=p).derive(passphrase.encode())


def _aad(header: bytes, index: int, last: bool) -> bytes:
    return header + struct.pack(">I?", index, last)


def _chunks(f: BinaryIO) -> Iterator[tuple[bytes, bool]]:
    cur = f.read(CHUNK)
    while True:
        nxt = f.read(CHUNK)
        yield cur, not nxt
        if not nxt:
            return
        cur = nxt


def encrypt_file(src: Path, dest: Path, passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE:
        raise ValueError(f"backup passphrase must be at least {MIN_PASSPHRASE} characters")
    salt, prefix = os.urandom(16), os.urandom(7)
    header = MAGIC + salt + bytes([LOG2_N, R, P]) + prefix
    aes = AESGCM(_key(passphrase, salt, LOG2_N, R, P))
    partial = dest.with_name(dest.name + ".partial")
    with src.open("rb") as fin, partial.open("wb") as fout:
        fout.write(header)
        for i, (data, last) in enumerate(_chunks(fin)):
            ct = aes.encrypt(prefix + struct.pack(">I", i), data, _aad(header, i, last))
            fout.write(struct.pack(">I", len(ct)) + ct)
    partial.chmod(0o600)
    partial.replace(dest)


def decrypt_file(src: Path, dest: Path, passphrase: str) -> None:
    """Decrypt to dest; nothing is left at dest unless every chunk authenticates."""
    partial = dest.with_name(dest.name + ".partial")
    try:
        with src.open("rb") as fin, partial.open("wb") as fout:
            header = fin.read(HEADER_LEN)
            if len(header) != HEADER_LEN or not header.startswith(MAGIC):
                raise DecryptError("not a Locuvi encrypted backup")
            salt = header[8:24]
            log2_n, r, p = header[24], header[25], header[26]
            prefix = header[27:34]
            aes = AESGCM(_key(passphrase, salt, log2_n, r, p))
            i, finished = 0, False
            while True:
                raw = fin.read(4)
                if not raw:
                    break
                if finished or len(raw) != 4:
                    raise DecryptError("backup file is damaged")
                (n,) = struct.unpack(">I", raw)
                ct = fin.read(n)
                if len(ct) != n or n > CHUNK + 16:
                    raise DecryptError("backup file is damaged")
                nonce = prefix + struct.pack(">I", i)
                for last in (False, True):
                    try:
                        fout.write(aes.decrypt(nonce, ct, _aad(header, i, last)))
                        finished = last
                        break
                    except InvalidTag:
                        continue
                else:
                    raise DecryptError("wrong passphrase or backup file is damaged")
                i += 1
            if not finished:
                raise DecryptError("backup file is incomplete")
        partial.chmod(0o600)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
