"""Stand-ins for Dropbox, OneDrive and Google Drive (only what Locuvi uses), in memory.

They behave like the real services where it matters to sync: sign-in tokens that run out
and get renewed, a refused write when someone else's version is there now, OneDrive's
upload sessions and download redirects, Google's multipart and resumable uploads. Never a
real account. Fictional data only.
"""

from __future__ import annotations

import itertools
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

EMAIL = "alex@example.invalid"


class FakeCloud:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.files: dict[str, tuple[bytes, str]] = {}  # dropbox/onedrive: path -> (data, version)
        self.access = {"at-1"}
        self.valid_refresh: set[str] = set()  # each sign-in gets its own
        self.refreshes = 0
        self._n = itertools.count(2)
        # google: id -> {name, parents, mime, data, created}
        self.g: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.requests: list[str] = []

    def expire_access(self) -> None:
        self.access = set()

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=True)

    # ------------------------------------------------------------------ shared

    def _json(self, data: object, status: int = 200, **headers: str) -> httpx.Response:
        return httpx.Response(status, json=data, headers=headers)

    def _token(self, req: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != "good-code" or len(form.get("code_verifier", "")) < 43:
                return self._json({"error": "invalid_grant"}, 400)
            refresh = f"rt-{next(self._n)}"
            self.valid_refresh.add(refresh)
        elif form.get("grant_type") == "refresh_token":
            refresh = form.get("refresh_token", "")
            if refresh not in self.valid_refresh:
                return self._json({"error": "invalid_grant"}, 400)
            self.refreshes += 1
            if self.provider == "onedrive":  # Microsoft replaces the refresh token each time
                self.valid_refresh.discard(refresh)
                refresh = f"rt-{next(self._n)}"
                self.valid_refresh.add(refresh)
        else:
            return self._json({"error": "unsupported_grant_type"}, 400)
        access = f"at-{next(self._n)}"
        self.access.add(access)
        return self._json({"access_token": access, "refresh_token": refresh,
                           "expires_in": 3600, "token_type": "bearer"})  # fmt: skip

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(f"{req.method} {req.url.host}{req.url.path}")
        if req.url.path.endswith("/token"):
            return self._token(req)
        if req.url.host in ("dl.example.invalid", "up.example.invalid"):
            return self._onedrive_unsigned(req)
        if req.headers.get("Authorization", "").removeprefix("Bearer ") not in self.access:
            return self._json({"error": "expired"}, 401)
        return getattr(self, f"_{self.provider}")(req)

    # ------------------------------------------------------------------ Dropbox

    def _dropbox(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/2/users/get_current_account":
            return self._json({"email": EMAIL})
        arg = json.loads(req.headers.get("Dropbox-API-Arg", "{}"))
        if path == "/2/files/download":
            got = self.files.get(arg["path"])
            if got is None:
                return self._json({"error_summary": "path/not_found/"}, 409)
            result = {"Dropbox-API-Result": json.dumps({"rev": got[1]})}
            return httpx.Response(200, content=got[0], headers=result)
        if path == "/2/files/upload":
            mode, now = arg["mode"], self.files.get(arg["path"])
            if mode[".tag"] == "add" and now is not None:
                return self._json({"error_summary": "path/conflict/file/"}, 409)
            if mode[".tag"] == "update" and (now is None or now[1] != mode["update"]):
                return self._json({"error_summary": "path/conflict/file/"}, 409)
            rev = f"rev{next(self._n)}"
            self.files[arg["path"]] = (req.content, rev)
            return self._json({"rev": rev})
        body = json.loads(req.content or b"{}")
        if path == "/2/files/list_folder":
            folder = body["path"].rstrip("/") + "/"
            names = [p[len(folder) :] for p in self.files if p.startswith(folder)]
            if not names:
                return self._json({"error_summary": "path/not_found/"}, 409)
            # two pages, to exercise list_folder/continue
            half = len(names) // 2
            entries = [{".tag": "file", "name": n} for n in names[:half]]
            self._rest = [{".tag": "file", "name": n} for n in names[half:]]
            return self._json({"entries": entries, "has_more": True, "cursor": "c1"})
        if path == "/2/files/list_folder/continue":
            return self._json({"entries": self._rest, "has_more": False, "cursor": "c2"})
        return self._json({}, 404)

    # ------------------------------------------------------------------ OneDrive

    def _onedrive(self, req: httpx.Request) -> httpx.Response:
        path = unquote(req.url.path)
        if path == "/v1.0/me":
            return self._json({"mail": EMAIL})
        m = re.fullmatch(r"/v1\.0/me/drive/special/approot:/(.+?):(/.*)?", path)
        if not m:
            return self._json({}, 404)
        item, op = m.group(1), m.group(2) or ""
        now = self.files.get(item)
        if req.method == "GET" and op == "":
            if now is None:
                return self._json({}, 404)
            return self._json({"eTag": now[1], "@microsoft.graph.downloadUrl":
                               f"https://dl.example.invalid/{item}"})  # fmt: skip
        if req.method == "GET" and op == "/content":
            if now is None:
                return self._json({}, 404)
            return httpx.Response(302, headers={"Location": f"https://dl.example.invalid/{item}"})
        if req.method == "GET" and op == "/children":
            folder = item.rstrip("/") + "/"
            kids = [p[len(folder) :] for p in self.files if p.startswith(folder)]
            if not kids:
                return self._json({}, 404)
            return self._json({"value": [{"name": k, "file": {}} for k in kids]})
        conflict = req.url.params.get("@microsoft.graph.conflictBehavior", "replace")
        if_match = req.headers.get("If-Match")
        if req.method == "POST" and op == "/createUploadSession":
            conflict = json.loads(req.content)["item"]["@microsoft.graph.conflictBehavior"]
        if if_match and (now is None or now[1] != if_match):
            return self._json({}, 412)
        if conflict == "fail" and now is not None:
            return self._json({}, 409)
        if req.method == "PUT" and op == "/content":
            etag = f"etag{next(self._n)}"
            self.files[item] = (req.content, etag)
            return self._json({"eTag": etag}, 201)
        if req.method == "POST" and op == "/createUploadSession":
            sid = f"s{next(self._n)}"
            self.sessions[sid] = {"item": item, "data": b""}
            return self._json({"uploadUrl": f"https://up.example.invalid/{sid}"})
        return self._json({}, 404)

    def _onedrive_unsigned(self, req: httpx.Request) -> httpx.Response:
        if "Authorization" in req.headers:  # these addresses must not get the token
            return self._json({"error": "unexpected token"}, 400)
        if req.url.host == "dl.example.invalid":
            got = self.files.get(unquote(req.url.path).lstrip("/"))
            return httpx.Response(200, content=got[0]) if got else self._json({}, 404)
        s = self.sessions[req.url.path.lstrip("/")]
        rng = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", req.headers["Content-Range"])
        assert rng and int(rng.group(1)) == len(s["data"])
        s["data"] += req.content
        if len(s["data"]) < int(rng.group(3)):
            return self._json({"nextExpectedRanges": [f"{len(s['data'])}-"]}, 202)
        etag = f"etag{next(self._n)}"
        self.files[s["item"]] = (s["data"], etag)
        return self._json({"eTag": etag}, 201)

    # ------------------------------------------------------------------ Google Drive

    def _new_file(self, meta: dict, data: bytes) -> dict:
        fid = f"g{next(self._n)}"
        f = {"id": fid, "name": meta["name"], "parents": meta.get("parents", ["root"]),
             "mime": meta.get("mimeType", "application/octet-stream"), "data": data,
             "createdTime": f"2026-10-23T12:00:{len(self.g):02d}.000Z"}  # fmt: skip
        self.g[fid] = f
        return f

    def _google(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/drive/v3/about":
            return self._json({"user": {"emailAddress": EMAIL}})
        if path == "/drive/v3/files" and req.method == "GET":
            q = req.url.params["q"]
            hits = [f for f in self.g.values() if self._matches(f, q)]
            hits.sort(key=lambda f: f["createdTime"])
            return self._json({"files": [{k: f[k] for k in ("id", "name", "createdTime")}
                                         for f in hits]})  # fmt: skip
        if path == "/drive/v3/files" and req.method == "POST":
            return self._json({"id": self._new_file(json.loads(req.content), b"")["id"]})
        m = re.fullmatch(r"/drive/v3/files/(\w+)", path)
        if m:
            f = self.g.get(m.group(1))
            if f is None:
                return self._json({}, 404)
            if req.method == "DELETE":
                del self.g[f["id"]]
                return httpx.Response(204)
            return httpx.Response(200, content=f["data"])
        if path == "/upload/drive/v3/files":
            kind = req.url.params.get("uploadType")
            if kind == "multipart":
                boundary = req.headers["Content-Type"].split("boundary=")[1]
                parts = req.content.split(f"--{boundary}".encode())
                meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
                data = parts[2].split(b"\r\n\r\n", 1)[1][:-2]
                f = self._new_file(meta, data)
                return self._json({"id": f["id"], "createdTime": f["createdTime"]})
            if kind == "resumable" and req.method == "POST":
                sid = f"u{next(self._n)}"
                self.sessions[sid] = json.loads(req.content)
                url = f"https://www.googleapis.com/upload/drive/v3/files?upload_id={sid}"
                return httpx.Response(200, headers={"Location": url})
            if req.method == "PUT":
                f = self._new_file(self.sessions.pop(req.url.params["upload_id"]), req.content)
                return self._json({"id": f["id"], "createdTime": f["createdTime"]})
        return self._json({}, 404)

    @staticmethod
    def _matches(f: dict, q: str) -> bool:
        for parent in re.findall(r"'([\w]+)' in parents", q):
            if parent not in f["parents"]:
                return False
        name = re.search(r"name = '([^']+)'", q)
        if name and f["name"] != name.group(1):
            return False
        part = re.search(r"name contains '([^']+)'", q)
        if part and part.group(1) not in f["name"]:
            return False
        if "mimeType = 'application/vnd.google-apps.folder'" in q:
            return f["mime"] == "application/vnd.google-apps.folder"
        return True


def path_of(url: str) -> str:
    return urlsplit(url).path
