"""Sync through a Dropbox, Google Drive or OneDrive account (no app needed on the device).

Signing in (OAuth 2 with PKCE, ``begin`` and ``finish``): Locuvi sends the person to the
company's own sign-in page; the company sends them back to Locuvi's return page
(``cloud_apps.RETURN_PAGE``), which hands the one-time code to the Locuvi that asked:
the computer app (``local:<port>``), the Android app (``app``, through ``locuvi://oauth``)
or the iPhone/iPad site (``web``). Locuvi swaps the code for a long-lived *refresh token*,
kept encrypted with this device's sync settings like a saved password; nothing about the
account is stored anywhere else.

Each company only gets Locuvi's own folder: Dropbox's "Apps/<app>" folder, OneDrive's app
folder, and on Google Drive only the files Locuvi itself made ("Locuvi Sync" in My Drive).
What's stored there is the same encrypted sync folder as anywhere else (``targets.py``).

Requests go through httpx; in the phone app through the app or browser
(``webdav.browser.BrowserTransport``), so they work there too.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets as pysecrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from locuvi import cloud_apps
from locuvi.errors import DomainError
from locuvi.sync.targets import FOLDER, STATE, TargetError, _check_name

PROVIDERS = ("dropbox", "google", "onedrive")
NAMES = {"dropbox": "Dropbox", "google": "Google Drive", "onedrive": "OneDrive"}
SIMPLE_UPLOAD = 4 * 1024 * 1024  # bigger files go up in parts (OneDrive, Google)
CHUNK = 16 * 327_680  # 5 MiB, a multiple of OneDrive's 320 KiB


def available() -> list[str]:
    """The providers this copy of Locuvi is set up for (cloud_apps)."""
    return [p for p in PROVIDERS if cloud_apps.client(p)[0]]


# Someone's own registered app (docs/CLOUD_APPS.md), used instead of Locuvi's: (id, secret).
OwnApp = tuple[str, str]
_OWN_ID = re.compile(r"[A-Za-z0-9._-]{8,200}")
_OWN_SECRET = re.compile(r"[A-Za-z0-9._~-]{0,200}")


def own_app(provider: str, client_id: str | None, secret: str | None) -> OwnApp | None:
    """Check an app key typed in Settings: None when none was given."""
    cid, sec = (client_id or "").strip(), (secret or "").strip()
    if not cid:
        return None
    if not _OWN_ID.fullmatch(cid) or not _OWN_SECRET.fullmatch(sec):
        raise DomainError("sync.cloud_own_app", "That app key doesn't look right. Copy it again.")
    if provider == "google" and not sec:
        raise DomainError("sync.cloud_own_secret", "Google also needs the app's client secret.")
    return cid, sec


def _http() -> httpx.Client:
    transport = None
    if os.environ.get("LOCUVI_POCKET") == "1":
        from locuvi.webdav.browser import BrowserTransport

        transport = BrowserTransport()
    return httpx.Client(timeout=60, follow_redirects=True, transport=transport)


# ------------------------------------------------------------------ signing in

AUTHORIZE = {
    "dropbox": "https://www.dropbox.com/oauth2/authorize",
    "google": "https://accounts.google.com/o/oauth2/v2/auth",
    "onedrive": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
}
TOKEN = {
    "dropbox": "https://api.dropboxapi.com/oauth2/token",
    "google": "https://oauth2.googleapis.com/token",
    "onedrive": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
}
SCOPE = {
    "dropbox": "",  # the app's permissions, set in its Dropbox settings
    "google": "https://www.googleapis.com/auth/drive.file",
    "onedrive": "Files.ReadWrite.AppFolder offline_access User.Read",
}


def _check(provider: str, own: OwnApp | None = None) -> tuple[str, str]:
    if provider in PROVIDERS and own:
        return own
    if provider not in PROVIDERS or not cloud_apps.client(provider)[0]:
        raise DomainError("sync.cloud_unavailable", "That cloud storage isn't available here.")
    return cloud_apps.client(provider)


def _check_return(return_to: str) -> str:
    port = return_to.removeprefix("local:")
    if return_to in ("web", "app") or (
        return_to.startswith("local:") and port.isdigit() and 0 < int(port) < 65536
    ):
        return return_to
    raise DomainError("sync.cloud_return", "Locuvi can't come back to this address.")


def redirect_uri(provider: str, return_to: str) -> str:
    if provider == "onedrive" and return_to != "web":
        return cloud_apps.RETURN_PAGE_NATIVE
    return cloud_apps.RETURN_PAGE


def begin(provider: str, return_to: str, own: OwnApp | None = None) -> dict[str, str]:
    """The company's sign-in address, and what to keep until the person comes back.
    ``own``: the person's own registered app instead of Locuvi's."""
    cid, _ = _check(provider, own)
    _check_return(return_to)
    verifier = pysecrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    state = f"{pysecrets.token_urlsafe(16)}.{return_to}"
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri(provider, return_to),
        "state": state,
        "code_challenge": challenge.decode().rstrip("="),
        "code_challenge_method": "S256",
    }
    if provider == "dropbox":
        params["token_access_type"] = "offline"
    elif provider == "google":
        params.update(scope=SCOPE["google"], access_type="offline", prompt="consent")
    else:
        params.update(scope=SCOPE["onedrive"], prompt="select_account")
    return {"url": f"{AUTHORIZE[provider]}?{urlencode(params)}", "state": state,
            "verifier": verifier}  # fmt: skip


def _token_request(provider: str, form: dict[str, str], return_to: str,
                   http: httpx.Client, own: OwnApp | None = None) -> dict[str, Any]:  # fmt: skip
    cid, secret = _check(provider, own)
    form = {**form, "client_id": cid}
    if secret:
        form["client_secret"] = secret
    if provider == "onedrive":
        form["scope"] = SCOPE["onedrive"]
    try:
        r = http.post(TOKEN[provider], data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        raise TargetError("sync.cloud_offline", f"{NAMES[provider]} can't be reached.") from None
    if r.status_code >= 400:
        raise TargetError(
            "sync.cloud_signin",
            f"{NAMES[provider]} didn't accept the sign-in. Please sign in again.",
        )
    return r.json()


def finish(provider: str, code: str, verifier: str, return_to: str,
           http: httpx.Client | None = None,
           own: OwnApp | None = None) -> dict[str, Any]:  # fmt: skip
    """Swap the one-time code for lasting access; returns the account and refresh token."""
    _check_return(return_to)
    opened = http is None
    http = http or _http()
    try:
        tok = _token_request(provider, {
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": redirect_uri(provider, return_to),
        }, return_to, http, own)  # fmt: skip
        refresh = tok.get("refresh_token")
        if not refresh:
            raise TargetError(
                "sync.cloud_signin", f"{NAMES[provider]} didn't allow lasting access."
            )
        account = _account(provider, tok["access_token"], http)
    finally:
        if opened:
            http.close()
    return {"provider": provider, "refresh": refresh, "return_to": return_to,
            "account": account, "access": tok["access_token"], "own": own,
            "expires": time.time() + float(tok.get("expires_in", 3600)) - 60}  # fmt: skip


def _account(provider: str, access: str, http: httpx.Client) -> str:
    h = {"Authorization": f"Bearer {access}"}
    try:
        if provider == "dropbox":
            r = http.post("https://api.dropboxapi.com/2/users/get_current_account", headers=h)
            return str(r.json().get("email", ""))
        if provider == "google":
            r = http.get("https://www.googleapis.com/drive/v3/about",
                         params={"fields": "user(emailAddress)"}, headers=h)  # fmt: skip
            return str(r.json().get("user", {}).get("emailAddress", ""))
        r = http.get("https://graph.microsoft.com/v1.0/me", headers=h)
        d = r.json()
        return str(d.get("mail") or d.get("userPrincipalName") or "")
    except (httpx.HTTPError, ValueError):
        return ""


# ------------------------------------------------------------------ staying signed in


class Session:
    """An access token for one account, renewed from the refresh token when it runs out.

    ``on_refresh`` saves a new refresh token when the company replaces it (Microsoft does).
    ``own``: the app it was signed in with, when it's the person's own (a sign-in only
    renews with the app that made it)."""

    _cache: dict[str, tuple[str, float]] = {}
    _lock = threading.Lock()

    def __init__(self, provider: str, refresh: str, return_to: str, *, on_refresh=None,
                 http: httpx.Client | None = None, own: OwnApp | None = None) -> None:  # type: ignore[no-untyped-def]  # fmt: skip
        self.provider, self.refresh, self.return_to = provider, refresh, return_to
        self.own = own
        self.on_refresh = on_refresh
        self.http = http or _http()
        self._key = hashlib.sha256(refresh.encode()).hexdigest()

    def token(self, renew: bool = False) -> str:
        with self._lock:
            hit = self._cache.get(self._key)
            if hit and not renew and hit[1] > time.time():
                return hit[0]
            tok = _token_request(self.provider, {
                "grant_type": "refresh_token", "refresh_token": self.refresh,
            }, self.return_to, self.http, self.own)  # fmt: skip
            new_refresh = tok.get("refresh_token")
            if new_refresh and new_refresh != self.refresh:
                self.refresh = new_refresh
                self._key = hashlib.sha256(new_refresh.encode()).hexdigest()
                if self.on_refresh:
                    self.on_refresh(new_refresh)
            exp = time.time() + float(tok.get("expires_in", 3600)) - 60
            self._cache[self._key] = (tok["access_token"], exp)
            return tok["access_token"]

    def request(self, method: str, url: str, *, auth: bool = True, **kw: Any) -> httpx.Response:
        """One request, signed in; a refused token is renewed once."""
        for attempt in (0, 1):
            headers = dict(kw.pop("headers", None) or {})
            if auth:
                headers["Authorization"] = f"Bearer {self.token(renew=attempt == 1)}"
            try:
                r = self.http.request(method, url, headers=headers, **kw)
            except httpx.HTTPError:
                raise TargetError(
                    "sync.cloud_offline", f"{NAMES[self.provider]} can't be reached."
                ) from None
            kw["headers"] = {k: v for k, v in headers.items() if k != "Authorization"}
            if r.status_code != 401 or not auth or attempt == 1:
                break
        if r.status_code == 401:
            raise TargetError(
                "sync.cloud_signin",
                f"{NAMES[self.provider]} signed Locuvi out. Sync again after signing in "
                "(Settings › Sync and backup file).",
            )
        if r.status_code == 429 or r.status_code >= 500:
            raise TargetError("sync.cloud_busy", f"{NAMES[self.provider]} is busy. Try again soon.")
        return r


def _fail(r: httpx.Response, what: str) -> TargetError:
    return TargetError("sync.cloud_error", f"Sync couldn't {what} (HTTP {r.status_code}).")


# ------------------------------------------------------------------ Dropbox

DBX = "https://api.dropboxapi.com/2"
DBX_CONTENT = "https://content.dropboxapi.com/2"


class DropboxTarget:
    """Dropbox: Locuvi's app folder ("Apps/<app name>"), with each file's revision as its
    version (an upload names the revision it replaces, or fails)."""

    def __init__(self, session: Session, label: str) -> None:
        self.s, self.label = session, label
        self.root = f"/{FOLDER}"

    def _arg(self, **arg: Any) -> dict[str, str]:
        return {"Dropbox-API-Arg": json.dumps(arg, ensure_ascii=True)}

    def _download(self, path: str) -> tuple[bytes, str] | None:
        r = self.s.request("POST", f"{DBX_CONTENT}/files/download", headers=self._arg(path=path))
        if r.status_code == 409:
            return None  # not there (yet)
        if r.status_code != 200:
            raise _fail(r, "read from Dropbox")
        meta = json.loads(r.headers.get("Dropbox-API-Result", "{}"))
        return r.content, str(meta.get("rev", ""))

    def _upload(self, path: str, data: bytes, rev: str | None) -> bool:
        mode = {".tag": "update", "update": rev} if rev else {".tag": "add"}
        headers = {**self._arg(path=path, mode=mode, autorename=False, mute=True),
                   "Content-Type": "application/octet-stream"}  # fmt: skip
        r = self.s.request("POST", f"{DBX_CONTENT}/files/upload", headers=headers, content=data)
        if r.status_code == 409:
            return False  # someone else's version is there now
        if r.status_code != 200:
            raise _fail(r, "save to Dropbox")
        return True

    def read_state(self) -> tuple[bytes, str] | None:
        return self._download(f"{self.root}/{STATE}")

    def write_state(self, data: bytes, version: str | None) -> bool:
        return self._upload(f"{self.root}/{STATE}", data, version)

    def blob_names(self) -> set[str]:
        names: set[str] = set()
        r = self.s.request("POST", f"{DBX}/files/list_folder",
                           json={"path": f"{self.root}/blobs", "limit": 2000})  # fmt: skip
        while True:
            if r.status_code == 409:
                return names  # no files yet
            if r.status_code != 200:
                raise _fail(r, "list Dropbox")
            d = r.json()
            names |= {e["name"] for e in d.get("entries", []) if e.get(".tag") == "file"}
            if not d.get("has_more"):
                return names
            r = self.s.request("POST", f"{DBX}/files/list_folder/continue",
                               json={"cursor": d["cursor"]})  # fmt: skip

    def read_blob(self, name: str) -> bytes:
        got = self._download(f"{self.root}/blobs/{_check_name(name)}")
        if got is None:
            raise TargetError("sync.blob_missing", "A file is missing from the sync folder.")
        return got[0]

    def write_blob(self, name: str, data: bytes) -> None:
        self._upload(f"{self.root}/blobs/{_check_name(name)}", data, None)  # there already: fine


# ------------------------------------------------------------------ OneDrive

GRAPH = "https://graph.microsoft.com/v1.0/me/drive/special/approot"


class OneDriveTarget:
    """OneDrive: Locuvi's app folder ("Apps/Locuvi"), with each file's eTag as its version
    (an upload names the eTag it replaces with If-Match, or must be the first)."""

    def __init__(self, session: Session, label: str) -> None:
        self.s, self.label = session, label

    def _item(self, *parts: str) -> str:
        path = "/".join(quote(p) for p in (FOLDER, *parts))
        return f"{GRAPH}:/{path}:"

    def read_state(self) -> tuple[bytes, str] | None:
        r = self.s.request("GET", self._item(STATE))
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise _fail(r, "read from OneDrive")
        meta = r.json()
        got = self.s.request("GET", meta["@microsoft.graph.downloadUrl"], auth=False)
        if got.status_code != 200:
            raise _fail(got, "read from OneDrive")
        return got.content, str(meta.get("eTag", ""))

    def _put(self, parts: tuple[str, ...], data: bytes, etag: str | None, replace: bool) -> bool:
        conflict = "replace" if replace else "fail"
        headers = {"If-Match": etag} if etag else {}
        if len(data) <= SIMPLE_UPLOAD:
            r = self.s.request(
                "PUT", f"{self._item(*parts)}/content",
                params={"@microsoft.graph.conflictBehavior": conflict},
                headers={**headers, "Content-Type": "application/octet-stream"}, content=data,
            )  # fmt: skip
            if r.status_code in (409, 412):
                return False
            if r.status_code not in (200, 201):
                raise _fail(r, "save to OneDrive")
            return True
        body = {"item": {"@microsoft.graph.conflictBehavior": conflict}}
        r = self.s.request(
            "POST", f"{self._item(*parts)}/createUploadSession", headers=headers, json=body
        )
        if r.status_code in (409, 412):
            return False
        if r.status_code != 200:
            raise _fail(r, "save to OneDrive")
        url = r.json()["uploadUrl"]
        for start in range(0, len(data), CHUNK):
            part = data[start : start + CHUNK]
            end = start + len(part) - 1
            r = self.s.request("PUT", url, auth=False, content=part, headers={
                "Content-Range": f"bytes {start}-{end}/{len(data)}"})  # fmt: skip
            if r.status_code in (409, 412):
                return False
            if r.status_code not in (200, 201, 202):
                raise _fail(r, "save to OneDrive")
        return True

    def write_state(self, data: bytes, version: str | None) -> bool:
        return self._put((STATE,), data, version, replace=bool(version))

    def blob_names(self) -> set[str]:
        names: set[str] = set()
        url: str | None = f"{self._item('blobs')}/children"
        params: dict[str, str] | None = {"$select": "name,file", "$top": "999"}
        while url:
            r = self.s.request("GET", url, params=params)
            if r.status_code == 404:
                return names
            if r.status_code != 200:
                raise _fail(r, "list OneDrive")
            d = r.json()
            names |= {i["name"] for i in d.get("value", []) if "file" in i}
            url, params = d.get("@odata.nextLink"), None
        return names

    def read_blob(self, name: str) -> bytes:
        r = self.s.request("GET", f"{self._item('blobs', _check_name(name))}/content")
        if r.status_code == 404:
            raise TargetError("sync.blob_missing", "A file is missing from the sync folder.")
        if r.status_code != 200:
            raise _fail(r, "read from OneDrive")
        return r.content

    def write_blob(self, name: str, data: bytes) -> None:
        self._put(("blobs", _check_name(name)), data, None, replace=False)


# ------------------------------------------------------------------ Google Drive

DRIVE = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class _Copy:
    seq: int
    id: str
    created: str


class GoogleDriveTarget:
    """Google Drive: a "Locuvi Sync" folder in My Drive that only Locuvi can see into
    (``drive.file``).

    Google can't refuse a write that lands on a newer copy, so each sync writes a new
    ``state-<n>.lcv`` and the version is n: a write expects the newest to be the n it read,
    and if two devices wrote the same n at once, the earliest file wins and the other device
    removes its own and merges again. Old copies are tidied away."""

    def __init__(self, session: Session, label: str) -> None:
        self.s, self.label = session, label
        self._ids: dict[str, str] = {}

    def _q(self, q: str, fields: str = "files(id,name,createdTime)") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        token = None
        while True:
            params = {"q": q, "fields": f"nextPageToken,{fields}", "pageSize": "1000",
                      "orderBy": "createdTime", "spaces": "drive"}  # fmt: skip
            if token:
                params["pageToken"] = token
            r = self.s.request("GET", DRIVE, params=params)
            if r.status_code != 200:
                raise _fail(r, "list Google Drive")
            d = r.json()
            out += d.get("files", [])
            token = d.get("nextPageToken")
            if not token:
                return out

    def _folder(self, name: str, parent: str | None) -> str:
        key = f"{parent}/{name}"
        if key in self._ids:
            return self._ids[key]
        q = f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        q += f" and '{parent}' in parents" if parent else " and 'root' in parents"
        found = self._q(q)
        if found:
            fid = found[0]["id"]  # two devices made one at once: the first is used
        else:
            meta = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent or "root"]}
            r = self.s.request("POST", DRIVE, json=meta, params={"fields": "id"})
            if r.status_code != 200:
                raise _fail(r, "make a folder in Google Drive")
            fid = r.json()["id"]
        self._ids[key] = fid
        return fid

    def _root(self) -> str:
        return self._folder(FOLDER, None)

    def _upload(self, name: str, parent: str, data: bytes) -> str:
        meta = json.dumps({"name": name, "parents": [parent]})
        if len(data) <= SIMPLE_UPLOAD:
            boundary = "locuvi" + pysecrets.token_hex(8)
            body = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}"
                f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
            ).encode()
            body += data + f"\r\n--{boundary}--".encode()  # fmt: skip
            kind = f"multipart/related; boundary={boundary}"
            r = self.s.request(
                "POST",
                DRIVE_UPLOAD,
                content=body,
                headers={"Content-Type": kind},
                params={"uploadType": "multipart", "fields": "id,createdTime"},
            )
        else:
            kind = "application/json; charset=UTF-8"
            r = self.s.request(
                "POST",
                DRIVE_UPLOAD,
                content=meta.encode(),
                params={"uploadType": "resumable"},
                headers={"Content-Type": kind},
            )
            if r.status_code != 200:
                raise _fail(r, "save to Google Drive")
            # the upload address carries Google's own upload_id: add to it, don't replace it
            r = self.s.request("PUT", r.headers["Location"] + "&fields=id,createdTime",
                               content=data)  # fmt: skip
        if r.status_code not in (200, 201):
            raise _fail(r, "save to Google Drive")
        return str(r.json()["id"])

    def _copies(self) -> list[_Copy]:
        q = f"'{self._root()}' in parents and name contains 'state-' and trashed = false"
        found = self._q(q)
        out = []
        for f in found:
            n = f["name"].removeprefix("state-").removesuffix(".lcv")
            if n.isdigit():
                out.append(_Copy(int(n), f["id"], f.get("createdTime", "")))
        return sorted(out, key=lambda c: (-c.seq, c.created, c.id))

    def _download(self, fid: str) -> bytes:
        r = self.s.request("GET", f"{DRIVE}/{fid}", params={"alt": "media"})
        if r.status_code != 200:
            raise _fail(r, "read from Google Drive")
        return r.content

    def read_state(self) -> tuple[bytes, str] | None:
        copies = self._copies()
        if not copies:
            return None
        return self._download(copies[0].id), str(copies[0].seq)

    def write_state(self, data: bytes, version: str | None) -> bool:
        copies = self._copies()
        newest = copies[0].seq if copies else None
        if (str(newest) if newest is not None else None) != version:
            return False
        seq = (newest or 0) + 1
        mine = self._upload(f"state-{seq:010d}.lcv", self._root(), data)
        same = [c for c in self._copies() if c.seq == seq]
        if same and same[0].id != mine:  # another device wrote this number first
            self.s.request("DELETE", f"{DRIVE}/{mine}")
            return False
        for old in copies[2:]:  # keep the two before this one, for a device mid-read
            self.s.request("DELETE", f"{DRIVE}/{old.id}")
        return True

    def _blobs(self) -> str:
        return self._folder("blobs", self._root())

    def blob_names(self) -> set[str]:
        found = self._q(f"'{self._blobs()}' in parents and trashed = false", "files(id,name)")
        self._blob_ids = {f["name"]: f["id"] for f in found}
        return set(self._blob_ids)

    def read_blob(self, name: str) -> bytes:
        _check_name(name)
        ids = getattr(self, "_blob_ids", None) or {}
        if name not in ids:
            self.blob_names()
            ids = self._blob_ids
        if name not in ids:
            raise TargetError("sync.blob_missing", "A file is missing from the sync folder.")
        return self._download(ids[name])

    def write_blob(self, name: str, data: bytes) -> None:
        _check_name(name)
        if name in (getattr(self, "_blob_ids", None) or {}):
            return
        self._blob_ids = {**(getattr(self, "_blob_ids", None) or {}),
                          name: self._upload(name, self._blobs(), data)}  # fmt: skip


TARGETS = {"dropbox": DropboxTarget, "google": GoogleDriveTarget, "onedrive": OneDriveTarget}
