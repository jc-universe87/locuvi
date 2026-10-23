"""Checks that the installed app updates itself (run by .github/workflows/release.yml).

    python update-test.py <app executable> <installer (.exe or .dmg)> <work dir>

A stand-in for GitHub's "latest release" offers the installer that was just built, as
version 99.0.0. The app is started (headless, its own records), asked to update through
/api/v1/updates/install like the Update now button, and must then: stop, install the new
version over itself, and open again by itself (seen by its instance.json in the usual Locuvi
folder). The reopened app is then stopped.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


def main(app: str, installer: str, work: str) -> int:
    inst = Path(installer)
    data = inst.read_bytes()
    release = {
        "tag_name": "v99.0.0",
        "html_url": "https://github.com/jc-universe87/locuvi/releases",
        "assets": [{
            "name": inst.name, "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "browser_download_url": "",
        }],
    }  # fmt: skip

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps(release).encode() if self.path == "/latest" else data
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    port = srv.server_address[1]
    release["assets"][0]["browser_download_url"] = f"http://127.0.0.1:{port}/{inst.name}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    w = Path(work)
    w.mkdir(parents=True, exist_ok=True)
    (w / "pw").write_text("e2e-pass")
    info = w / "info.json"
    usual = usual_root()
    (usual / "instance.json").unlink(missing_ok=True)
    env = {**os.environ, "LOCUVI_UPDATE_URL": f"http://127.0.0.1:{port}/latest"}
    proc = subprocess.Popen([app, "--headless", "--data-dir", str(w / "root"), "--password-file",
                             str(w / "pw"), "--info-file", str(info)], env=env)  # fmt: skip
    for _ in range(120):
        if info.is_file() and info.stat().st_size:
            break
        time.sleep(1)
    i = json.loads(info.read_text())
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPCookieProcessor(jar))  # fmt: skip
    op.open(i["open"], timeout=30).read()
    csrf = json.loads(op.open(i["url"] + "/api/v1/auth/session", timeout=30).read())["csrf_token"]
    st = json.loads(op.open(i["url"] + "/api/v1/updates?check=1", timeout=60).read())
    print("update offered:", st)
    if not (st.get("available") and st.get("latest") == "99.0.0"):
        print("FAIL the app didn't see the new version")
        return 1
    req = urllib.request.Request(i["url"] + "/api/v1/updates/install", data=b"", method="POST",
                                 headers={"X-CSRF-Token": csrf})  # fmt: skip
    print("install:", op.open(req, timeout=300).read().decode())
    try:
        proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        print("FAIL the app didn't stop for the update")
        proc.kill()
        return 1
    print("PASS the app stopped for the update")
    for _ in range(240):
        if (usual / "instance.json").is_file():
            break
        time.sleep(1)
    else:
        print("FAIL the updated app didn't open again")
        up = w / "root" / "updates"
        for f in [up / "update-start.log", up / "update.ps1", up / "update.log",
                  up / "setup.log", usual / "logs" / "locuvi.log"]:  # fmt: skip
            if f.is_file():
                print(f"--- {f}\n" + f.read_text(errors="replace")[-4000:])
        return 1
    again = json.loads((usual / "instance.json").read_text())
    print("PASS the updated app opened again by itself")
    base = f"http://127.0.0.1:{again['port']}"
    jar2 = urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    op2 = urllib.request.build_opener(urllib.request.ProxyHandler({}), jar2)
    op2.open(f"{base}/desktop/open?token={again['token']}", timeout=30).read()
    csrf2 = json.loads(op2.open(base + "/api/v1/auth/session", timeout=30).read())["csrf_token"]
    quit_req = urllib.request.Request(
        base + "/api/v1/desktop/quit", data=b"", method="POST", headers={"X-CSRF-Token": csrf2}
    )
    op2.open(quit_req, timeout=30).read()
    print("PASS updated by itself")
    return 0


def usual_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "Locuvi"
    return Path.home() / "Library" / "Application Support" / "Locuvi"


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
