"""Keeping this device and the sync folder in step.

One sync (``sync_now``):

1. read the encrypted copy from the sync folder (``state.lcv``), if there is one;
2. merge it into this device's records (``merge.merge``, three-way with the last agreed copy)
   and bring over PDFs and documents this device doesn't have yet;
3. write the merged result back, but only onto the copy that was read: if another device
   synced in between, start again from step 1.

Before an invoice or credit note is issued, a sync also takes a short *lease* in the sync
folder, so two devices can't hand out the same number; the lease is given back straight
after, and runs out by itself after a few minutes if a device disappears.

Everything in the sync folder is encrypted with the sync code (``backup_crypto``: scrypt and
AES-GCM), which never leaves the devices. Inside, a random data key encrypts each file, and
the household key that protects saved passwords travels too, so a second device can use the
email and Nextcloud settings without retyping them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import secrets as pysecrets
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from locuvi import backup_crypto
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.secrets_store import SecretBox
from locuvi.sync import merge as merge_mod
from locuvi.sync.targets import FolderTarget, Target, TargetError, WebDavTarget

log = logging.getLogger("locuvi.sync")

FORMAT = 1
SYNCED_FOLDERS = ("invoices/issued", "invoices/credit", "documents")
LEASE_MINUTES = 3
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to read out and type
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(settings: Settings) -> threading.Lock:
    """One sync at a time per profile (each profile has its own folder and records)."""
    key = str(Path(settings.data_dir).resolve())
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# ------------------------------------------------------------------ the sync code


def new_code() -> str:
    """A code like KQ7M-2XRT-9WHC-4PZB-LN6D: 100 bits, typed once on each device."""
    raw = "".join(pysecrets.choice(CODE_ALPHABET) for _ in range(20))
    return "-".join(raw[i : i + 4] for i in range(0, 20, 4))


def normalise_code(code: str) -> str:
    raw = "".join(c for c in (code or "").upper() if c.isalnum())
    raw = raw.replace("0", "O").replace("1", "I")
    if len(raw) != 20 or any(c not in CODE_ALPHABET for c in raw):
        raise DomainError("sync.code_format", "That doesn't look like a sync code.")
    return "-".join(raw[i : i + 4] for i in range(0, 20, 4))


# ------------------------------------------------------------------ local settings


def sync_dir(settings: Settings) -> Path:
    """This device's own sync settings and last agreed copy. Never synced itself."""
    return Path(settings.data_dir) / "sync"


@dataclass
class Config:
    device_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    device_name: str = ""
    target: dict[str, Any] | None = None  # {"kind": "folder", "path": …} or {"kind": "nextcloud"}
    code_ciphertext: str | None = None
    last_ok: str | None = None
    last_error: dict[str, str] | None = None
    last_changes: int = 0

    @property
    def enabled(self) -> bool:
        return bool(self.target and self.code_ciphertext)


def load_config(settings: Settings) -> Config:
    f = sync_dir(settings) / "config.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    known = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
    return Config(**known)


def save_config(settings: Settings, cfg: Config) -> None:
    d = sync_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "config.json.part"
    tmp.write_text(json.dumps(cfg.__dict__, indent=1), encoding="utf-8")
    os.replace(tmp, d / "config.json")


# ------------------------------------------------------------------ what's in the folder


@dataclass
class Remote:
    db_path: Path
    files: dict[str, dict[str, str]]  # path -> {"sha": …, "blob": …}
    meta: dict[str, Any]


def _blob_name(data_key: bytes, sha: str) -> str:
    return hmac.new(data_key, sha.encode(), hashlib.sha256).hexdigest()


def _seal_blob(data_key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return b"LCVB1" + nonce + AESGCM(data_key).encrypt(nonce, data, b"locuvi-blob")


def _open_blob(data_key: bytes, blob: bytes, sha: str) -> bytes:
    if not blob.startswith(b"LCVB1"):
        raise DomainError("sync.damaged", "A file in the sync folder is damaged.")
    try:
        data = AESGCM(data_key).decrypt(blob[5:17], blob[17:], b"locuvi-blob")
    except Exception:  # noqa: BLE001 - any failure means damaged or tampered
        raise DomainError("sync.damaged", "A file in the sync folder is damaged.") from None
    if hashlib.sha256(data).hexdigest() != sha:
        raise DomainError("sync.damaged", "A file in the sync folder is damaged.")
    return data


def _seal_state(work: Path, db_file: Path, files: dict, meta: dict, code: str) -> bytes:
    plain = work / "state.zip"
    with zipfile.ZipFile(plain, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(db_file, "db.sqlite")
        z.writestr("files.json", json.dumps(files))
        z.writestr("meta.json", json.dumps(meta))
    sealed = work / "state.lcv"
    backup_crypto.encrypt_file(plain, sealed, code)
    return sealed.read_bytes()


def _open_state(data: bytes, code: str, work: Path) -> Remote:
    sealed, plain = work / "remote.lcv", work / "remote.zip"
    sealed.write_bytes(data)
    try:
        backup_crypto.decrypt_file(sealed, plain, code)
    except backup_crypto.DecryptError:
        raise DomainError(
            "sync.wrong_code",
            "The sync code doesn't open the sync folder. Check you typed the code from your "
            "other device.",
        ) from None
    with zipfile.ZipFile(plain) as z:
        meta = json.loads(z.read("meta.json"))
        if meta.get("format", 0) > FORMAT:
            raise DomainError(
                "sync.update_needed",
                "Another device has a newer Locuvi. Update Locuvi on this device, then sync.",
            )
        files = json.loads(z.read("files.json"))
        z.extract("db.sqlite", work / "remote")
    return Remote(db_path=work / "remote" / "db.sqlite", files=files, meta=meta)


# ------------------------------------------------------------------ the database copies


def _snapshot(src: Path, dest: Path) -> None:
    """A consistent copy (SQLite backup API), without this device's own tables."""
    s = sqlite3.connect(src, timeout=30)
    d = sqlite3.connect(dest)
    with d:
        s.backup(d)
    s.close()
    d.execute("PRAGMA journal_mode=DELETE")
    have = {r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in merge_mod.LOCAL_TABLES - {"alembic_version"}:
        if t in have:
            d.execute(f'DELETE FROM "{t}"')
    d.commit()
    d.execute("VACUUM")
    d.close()


def _revision(path: Path) -> str | None:
    c = sqlite3.connect(path)
    try:
        row = c.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        c.close()


def _bring_up_to_date(path: Path) -> None:
    """Upgrade a copy made by an older Locuvi; refuse one made by a newer Locuvi."""
    from alembic.script import ScriptDirectory

    from locuvi import db, migrate

    script = ScriptDirectory.from_config(migrate.alembic_config())
    known = {r.revision for r in script.walk_revisions()}
    rev = _revision(path)
    if rev is not None and rev not in known:
        raise DomainError(
            "sync.update_needed",
            "Another device has a newer Locuvi. Update Locuvi on this device, then sync.",
        )
    if rev != script.get_current_head():
        eng = db.make_engine(path)
        try:
            migrate.upgrade(eng)
        finally:
            eng.dispose()


# ------------------------------------------------------------------ files


def _scan(settings: Settings) -> dict[str, str]:
    from locuvi.storage.local import sha256_file

    root = Path(settings.data_dir)
    out = {}
    for folder in SYNCED_FOLDERS:
        d = root / folder
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and not f.name.startswith("."):
                out[f"{folder}/{f.name}"] = sha256_file(f)
    return out


def _safe_rel(rel: str) -> str:
    parts = rel.split("/")
    folder = "/".join(parts[:-1])
    if folder not in SYNCED_FOLDERS or not parts[-1] or parts[-1].startswith(".") or "\\" in rel:
        raise DomainError("sync.damaged", "The sync folder lists an unexpected file.")
    return rel


def _merge_files(
    settings: Settings,
    target: Target,
    data_key: bytes,
    base: dict[str, str],
    remote: dict[str, dict[str, str]],
) -> int:
    local = _scan(settings)
    root = Path(settings.data_dir)
    changed = 0
    for rel in set(base) | set(local) | set(remote):
        b, lo = base.get(rel), local.get(rel)
        re_ = remote[rel]["sha"] if rel in remote else None
        if lo == re_ or (re_ == b):
            continue  # same, or only this device changed it (sent on the way back)
        if lo != b and lo is not None:
            continue  # changed on both: this device keeps its own (issued PDFs never change)
        dest = root / _safe_rel(rel)
        if re_ is None:
            dest.unlink(missing_ok=True)  # removed on the other device (a deleted document)
        else:
            data = _open_blob(data_key, target.read_blob(remote[rel]["blob"]), re_)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.part")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        changed += 1
    return changed


# ------------------------------------------------------------------ saved passwords


def _household_key(settings: Settings) -> bytes:
    from locuvi.secrets_store import _load_or_create_key

    return _load_or_create_key(settings)


def _adopt_household_key(settings: Settings, secrets: SecretBox, new_key: bytes) -> None:
    """Re-encrypt this device's saved passwords with the household key from the sync folder,
    then use that key from now on."""
    old_key = _household_key(settings)
    if old_key == new_key:
        return
    if settings.encryption_key_file is not None:
        raise DomainError(
            "sync.key_file",
            "This Locuvi uses a fixed key file (ENCRYPTION_KEY_FILE), so it can't join a sync "
            "folder started elsewhere. Start sync on this Locuvi and join from the others.",
        )
    root = Path(settings.data_dir)
    if not (root / "profiles.db").exists() and root.parent.name == "profiles":
        root = root.parent.parent
    others = [p for p in (root / "profiles").glob("*/locuvi.db")]
    if others:
        # one key protects every profile's saved passwords on this Locuvi
        raise DomainError(
            "sync.shared_key",
            "This Locuvi has several profiles, so it can't join a sync folder started "
            "elsewhere. Start sync here and join from your other devices instead.",
        )
    old, new = Fernet(old_key), Fernet(new_key)
    conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
            for c in [c for c in cols if c.endswith("_ciphertext")]:
                for rowid, value in conn.execute(
                    f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL'
                ).fetchall():
                    try:
                        plain = old.decrypt(value.encode())
                    except InvalidToken:
                        continue  # already under the new key, or unreadable either way
                    conn.execute(
                        f'UPDATE "{t}" SET "{c}" = ? WHERE rowid = ?',
                        (new.encrypt(plain).decode(), rowid),
                    )
        cfg = load_config(settings)
        if cfg.code_ciphertext:
            cfg.code_ciphertext = new.encrypt(old.decrypt(cfg.code_ciphertext.encode())).decode()
        saved = (cfg.target or {}).get("password_ciphertext")
        if saved:
            cfg.target["password_ciphertext"] = new.encrypt(old.decrypt(saved.encode())).decode()  # type: ignore[index]
        key_path = settings.key_dir / "locuvi.key"
        tmp = key_path.with_suffix(".sync")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(new_key)
        save_config(settings, cfg)
        os.replace(tmp, key_path)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    secrets.reset()


# ------------------------------------------------------------------ targets


def nextcloud_spec(
    settings: Settings,
    secrets: SecretBox,
    *,
    url: str,
    home_url: str | None,
    username: str,
    password: str | None,
) -> dict[str, Any]:
    """The Nextcloud to sync with, checked and with the app password encrypted.

    ``url`` is its usual address (from anywhere); ``home_url`` an optional second address that
    works at home or in the office. Each sync uses whichever answers. Without a password, the
    one saved in Settings › Nextcloud copies is used (same Nextcloud and user)."""
    from locuvi.webdav.urlguard import UrlBlocked, validate_base_url

    spec: dict[str, Any] = {"kind": "nextcloud", "username": username.strip()}
    for key, raw, home in (("url", url, False), ("home_url", home_url, True)):
        if key == "home_url" and not (raw or "").strip():
            continue
        try:
            spec[key] = validate_base_url(
                _webdav_address(raw, spec["username"]), settings, home=home
            ).url
        except UrlBlocked as exc:
            raise DomainError(f"sync.nextcloud_{key}", str(exc), reason=exc.reason) from None
    if not spec["username"]:
        raise DomainError("sync.nextcloud_username", "Type your Nextcloud user name.")
    if not password:
        saved = _saved_nextcloud(settings, secrets)
        if saved is None or saved[1] != spec["username"]:
            raise DomainError("sync.nextcloud_password", "Type an app password for Nextcloud.")
        password = saved[2]
    spec["password_ciphertext"] = secrets.encrypt(password)
    return spec


def _webdav_address(raw: str, username: str) -> str:
    """ "cloud.example.uk" → "https://cloud.example.uk/remote.php/dav/files/<user>/".

    A full WebDAV address (from Nextcloud's Files settings) is kept as it is."""
    from urllib.parse import quote, urlsplit

    raw = (raw or "").strip()
    if raw and "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.netloc and parts.path in ("", "/") and username:
        return f"{parts.scheme}://{parts.netloc}/remote.php/dav/files/{quote(username, safe='')}/"
    return raw


def _saved_nextcloud(settings: Settings, secrets: SecretBox) -> tuple[str, str, str] | None:
    """The Nextcloud connection from Settings › Nextcloud copies: address, user, password."""
    from locuvi import db
    from locuvi.models import StorageConfig
    from locuvi.webdav import archive

    with db.new_session() as s:
        sc = s.get(StorageConfig, 1)
        if sc is None or not sc.target_url or not sc.username:
            return None
        try:
            password = archive.get_password(archive.ArchiveContext(settings, secrets), sc)
        except Exception:  # no password saved, or it can't be read
            return None
        return sc.target_url, sc.username, password


def saved_nextcloud_hint(settings: Settings, secrets: SecretBox) -> dict[str, str] | None:
    """Address and user of the saved Nextcloud connection, to fill in the sync form."""
    saved = _saved_nextcloud(settings, secrets)
    return {"url": saved[0], "username": saved[1]} if saved else None


_reached: dict[str, str] = {}  # data dir -> which address answered last ("url"/"home_url")


def build_target(settings: Settings, secrets: SecretBox, cfg: Config) -> Target:
    t = cfg.target or {}
    if t.get("kind") == "folder":
        return FolderTarget(Path(t["path"]))
    if t.get("kind") == "nextcloud":
        from locuvi.webdav.client import WebDavClient
        from locuvi.webdav.urlguard import validate_base_path, validate_base_url

        if t.get("url"):
            user, password = t["username"], secrets.decrypt(t["password_ciphertext"])
            addresses = [(k, t[k]) for k in ("url", "home_url") if t.get(k)]
        else:  # set up before sync had its own Nextcloud details
            saved = _saved_nextcloud(settings, secrets)
            if saved is None:
                raise DomainError(
                    "sync.nextcloud_missing",
                    "Set up Nextcloud first (Settings › Nextcloud copies).",
                )
            addresses, user, password = [("url", saved[0])], saved[1], saved[2]
        key = str(Path(settings.data_dir).resolve())
        last = _reached.get(key)
        addresses.sort(key=lambda a: a[0] != last)  # the one that answered last time first
        for i, (which, url) in enumerate(addresses):
            vurl = validate_base_url(url, settings, home=which == "home_url")
            client = WebDavClient(vurl, user, password, settings)
            if i == len(addresses) - 1 or client.reachable():
                _reached[key] = which
                return WebDavTarget(client, validate_base_path("Locuvi"), vurl.host)
            client.close()
    raise DomainError("sync.not_set_up", "Sync isn't set up on this device.")


# ------------------------------------------------------------------ one sync


@dataclass
class Report:
    pulled: int = 0  # records and files changed on this device
    pushed: bool = False
    files: int = 0
    at: str = ""


def sync_now(
    settings: Settings,
    secrets: SecretBox,
    *,
    target: Target | None = None,
    lease: bool = False,
    release: bool = False,
) -> Report:
    """Run one sync. ``lease`` reserves numbering for this device; ``release`` gives it back."""
    with _lock_for(settings):
        cfg = load_config(settings)
        if not cfg.enabled:
            raise DomainError("sync.not_set_up", "Sync isn't set up on this device.")
        try:
            report = _sync(settings, secrets, cfg, target, lease=lease, release=release)
        except (DomainError, TargetError, merge_mod.SyncConflict) as exc:
            cfg = load_config(settings)
            cfg.last_error = {
                "code": exc.code,
                "message": exc.message,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            save_config(settings, cfg)
            raise
        cfg = load_config(settings)
        cfg.last_ok, cfg.last_error, cfg.last_changes = report.at, None, report.pulled
        save_config(settings, cfg)
        return report


def _sync(
    settings: Settings,
    secrets: SecretBox,
    cfg: Config,
    target: Target | None,
    *,
    lease: bool,
    release: bool,
) -> Report:
    target = target or build_target(settings, secrets, cfg)
    code = secrets.decrypt(cfg.code_ciphertext or "")
    sd = sync_dir(settings)
    base_db = sd / "base.db"
    base_files_f = sd / "base_files.json"
    report = Report()
    now = datetime.now(UTC)
    for _attempt in range(5):
        with tempfile.TemporaryDirectory(dir=sd) as tmp:
            work = Path(tmp)
            got = target.read_state()
            remote = _open_state(got[0], code, work) if got else None
            if remote is not None:
                meta = dict(remote.meta)
                held = meta.get("lease") or {}
                if (
                    lease
                    and held.get("device") not in (None, cfg.device_id)
                    and held.get("until", "") > now.isoformat()
                ):
                    raise DomainError(
                        "sync.busy",
                        "Your other device is issuing an invoice right now. Try again in a minute.",
                    )
                key = base64.b64decode(meta["household_key"])
                _adopt_household_key(settings, secrets, key)
                _bring_up_to_date(remote.db_path)
                have_base = base_db.is_file()
                if have_base:
                    _bring_up_to_date(base_db)
                lc = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
                bc = sqlite3.connect(base_db) if have_base else None
                rc = sqlite3.connect(remote.db_path)
                try:
                    res = merge_mod.merge(lc, bc, rc)
                finally:
                    lc.close()
                    rc.close()
                    if bc:
                        bc.close()
                data_key = base64.b64decode(meta["data_key"])
                base_files = json.loads(base_files_f.read_text()) if base_files_f.is_file() else {}
                report.files = _merge_files(settings, target, data_key, base_files, remote.files)
                report.pulled = res.total + report.files
                needs_push = res.remote_needs_update
            else:
                meta = {
                    "format": FORMAT,
                    "data_key": base64.b64encode(os.urandom(32)).decode(),
                    "household_key": base64.b64encode(_household_key(settings)).decode(),
                    "created_at": now.isoformat(timespec="seconds"),
                }
                data_key = base64.b64decode(meta["data_key"])
                needs_push = True

            # what goes back: this device's merged records and files
            snap = work / "db.sqlite"
            _snapshot(settings.db_path, snap)
            local_files = _scan(settings)
            known_blobs = target.blob_names()
            files = {}
            for rel, sha in local_files.items():
                name = _blob_name(data_key, sha)
                if name not in known_blobs:
                    data = (Path(settings.data_dir) / rel).read_bytes()
                    target.write_blob(name, _seal_blob(data_key, data))
                files[rel] = {"sha": sha, "blob": name}
            if remote is not None and files != remote.files:
                needs_push = True

            held = meta.get("lease") or {}
            if lease:
                meta["lease"] = {
                    "device": cfg.device_id,
                    "until": (now + timedelta(minutes=LEASE_MINUTES)).isoformat(),
                }
                needs_push = True
            elif release and held.get("device") == cfg.device_id:
                meta.pop("lease", None)
                needs_push = True

            if needs_push:
                meta.update(
                    written_by=cfg.device_id,
                    written_name=cfg.device_name,
                    written_at=now.isoformat(timespec="seconds"),
                )
                sealed = _seal_state(work, snap, files, meta, code)
                if not target.write_state(sealed, got[1] if got else None):
                    continue  # another device synced meanwhile: merge their copy too
                report.pushed = True
            shutil.copyfile(snap, base_db)
            base_files_f.write_text(json.dumps(local_files))
            report.at = now.isoformat(timespec="seconds")
            return report
    raise DomainError("sync.busy", "Your devices kept syncing at the same moment. Try again.")


# ------------------------------------------------------------------ setting it up


def start(
    settings: Settings, secrets: SecretBox, target_spec: dict[str, Any], device_name: str
) -> str:
    """Start syncing from this device into an empty sync folder. Returns the new sync code."""
    code = new_code()
    _setup(settings, secrets, target_spec, device_name, code, must_be_empty=True)
    return code


def join(
    settings: Settings,
    secrets: SecretBox,
    target_spec: dict[str, Any],
    device_name: str,
    code: str,
) -> Report:
    """Join a sync folder another device started, with its sync code."""
    return _setup(settings, secrets, target_spec, device_name, normalise_code(code))


def _setup(
    settings: Settings,
    secrets: SecretBox,
    target_spec: dict[str, Any],
    device_name: str,
    code: str,
    *,
    must_be_empty: bool = False,
) -> Report:
    old = load_config(settings)
    cfg = Config(
        device_id=old.device_id,
        device_name=(device_name or "").strip()[:60] or "This device",
        target=target_spec,
        code_ciphertext=secrets.encrypt(code),
    )
    target = build_target(settings, secrets, cfg)
    got = target.read_state()
    if must_be_empty and got is not None:
        raise DomainError(
            "sync.already_started",
            "Locuvi is already syncing in that folder. Choose Join and type the sync code "
            "from your other device.",
        )
    if not must_be_empty and got is None:
        raise DomainError(
            "sync.nothing_there",
            "There's no Locuvi sync in that folder yet. Check you chose the same folder as on "
            "your other device.",
        )
    if got is not None:
        with tempfile.TemporaryDirectory() as tmp:
            _open_state(got[0], code, Path(tmp))  # wrong code: stop before anything changes
    for f in ("base.db", "base_files.json"):
        (sync_dir(settings) / f).unlink(missing_ok=True)  # a fresh join has no agreed copy
    save_config(settings, cfg)
    try:
        return sync_now(settings, secrets, target=target)
    except BaseException:
        if must_be_empty or got is None:
            save_config(settings, old)
        raise


def stop(settings: Settings) -> None:
    """Stop syncing on this device. Its records stay; the sync folder is left as it is."""
    cfg = load_config(settings)
    save_config(settings, Config(device_id=cfg.device_id))
    for f in ("base.db", "base_files.json"):
        (sync_dir(settings) / f).unlink(missing_ok=True)


def status(settings: Settings) -> dict[str, Any]:
    cfg = load_config(settings)
    t = cfg.target or {}
    nextcloud = None
    if t.get("kind") == "nextcloud" and t.get("url"):
        nextcloud = {
            "url": t["url"],
            "home_url": t.get("home_url"),
            "username": t.get("username"),
            "reached": _reached.get(str(Path(settings.data_dir).resolve())),
        }
    return {
        "enabled": cfg.enabled,
        "kind": t.get("kind"),
        "folder": t.get("path") if t.get("kind") == "folder" else None,
        "nextcloud": nextcloud,
        "device_name": cfg.device_name,
        "last_ok": cfg.last_ok,
        "last_error": cfg.last_error,
        "last_changes": cfg.last_changes,
    }


def code_for_display(settings: Settings, secrets: SecretBox) -> str | None:
    cfg = load_config(settings)
    return secrets.decrypt(cfg.code_ciphertext) if cfg.code_ciphertext else None


# ------------------------------------------------------------------ one-file export


def export_everything(settings: Settings, passphrase: str) -> bytes:
    """Everything in one encrypted file: records (with this device's own settings removed),
    PDFs and documents. Import it on any Locuvi, or keep it as a backup."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        snap = work / "db.sqlite"
        _snapshot(settings.db_path, snap)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "db.sqlite")
            for rel in _scan(settings):
                z.write(Path(settings.data_dir) / rel, f"files/{rel}")
            z.writestr(
                "meta.json",
                json.dumps(
                    {
                        "format": FORMAT,
                        "kind": "export",
                        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                ),
            )
        plain, sealed = work / "x.zip", work / "x.locuvi"
        plain.write_bytes(buf.getvalue())
        backup_crypto.encrypt_file(plain, sealed, passphrase)
        return sealed.read_bytes()


def import_everything(settings: Settings, data: bytes, passphrase: str) -> int:
    """Add everything from an export to this device's records (a merge: nothing here is
    deleted, and where both have the same record the file's copy is kept). Returns the
    number of records and files brought in."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        sealed, plain = work / "x.locuvi", work / "x.zip"
        sealed.write_bytes(data)
        try:
            backup_crypto.decrypt_file(sealed, plain, passphrase)
        except backup_crypto.DecryptError:
            raise DomainError(
                "sync.wrong_passphrase",
                "That password doesn't open this file, or it isn't a Locuvi export.",
            ) from None
        with zipfile.ZipFile(plain) as z:
            meta = json.loads(z.read("meta.json"))
            if meta.get("format", 0) > FORMAT:
                raise DomainError(
                    "sync.update_needed",
                    "This file comes from a newer Locuvi. Update Locuvi, then import it.",
                )
            names = z.namelist()
            z.extract("db.sqlite", work / "in")
            root = Path(settings.data_dir)
            brought = 0
            for n in names:
                if not n.startswith("files/"):
                    continue
                rel = _safe_rel(n[len("files/") :])
                dest = root / rel
                if dest.exists():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
                brought += 1
        incoming = work / "in" / "db.sqlite"
        _bring_up_to_date(incoming)
        lc = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
        rc = sqlite3.connect(incoming)
        try:
            # no common base: like joining, the file's version wins a clash, nothing is deleted
            res = merge_mod.merge(lc, None, rc)
        finally:
            lc.close()
            rc.close()
        return res.total + brought
