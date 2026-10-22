"""Checks a running desktop app (started with --headless --info-file …).

Used by the release workflow on Windows and macOS, next to the full UI smoke test, for the
parts only the desktop app has: its window signs in by itself, the web app's files arrive with
the right types (Windows' registry often gets .js wrong), and the desktop settings answer.

    python selftest.py path/to/info.json
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import sys
import urllib.request


def main(info_path: str) -> int:
    info = json.load(open(info_path, encoding="utf-8"))
    base = info["url"]
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
    )

    def get(path: str) -> tuple[str, str, bytes]:
        with opener.open(base + path, timeout=30) as r:
            return r.geturl(), r.headers.get("content-type", ""), r.read()

    checks: list[tuple[str, bool]] = []
    _, _, body = get("/api/v1/auth/session")
    checks.append(("signed out before the window opens", json.loads(body)["authenticated"] is False))
    with opener.open(info["open"], timeout=30) as r:  # follows the redirect to /
        page = r.read().decode("utf-8", "replace")
    _, _, body = get("/api/v1/auth/session")
    checks.append(("window link signs in", json.loads(body)["authenticated"] is True))
    script = re.search(r'src="(/assets/[^"]+\.js)"', page)
    checks.append(("web app page served", bool(script)))
    if script:
        _, kind, _ = get(script.group(1))
        checks.append((f"script type is JavaScript ({kind})", kind.startswith("text/javascript")))
    _, kind, _ = get("/manifest.webmanifest")
    checks.append((f"home-screen manifest ({kind})", kind.startswith("application/manifest+json")))
    _, _, body = get("/api/v1/desktop")
    d = json.loads(body)
    checks.append(("desktop settings available", d.get("available") is True))
    checks.append(("phone access off by default", d.get("phone_access") is False))
    _, _, body = get("/api/v1/health/ready")
    checks.append(("database ready", b"ok" in body.lower() or b"ready" in body.lower()))
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
