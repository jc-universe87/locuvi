"""Gather what the phone app needs to run Locuvi's backend, for pocket/assemble.mjs.

    python pocket/deps.py OUT_DIR

- OUT_DIR/pyodide/: the Pyodide release (PYODIDE_VERSION below), from GitHub;
- OUT_DIR/wheels/: Locuvi's own wheel, plus every package from backend/uv.lock that Pyodide
  doesn't build itself, at the locked version, as pure-Python wheels.

Packages Pyodide builds (pydantic, SQLAlchemy, cryptography, lxml, Pillow…) come from Pyodide,
compiled for the browser. The server and the phone run the same Locuvi code.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

PYODIDE_VERSION = "314.0.7"
PYODIDE_URL = (
    "https://github.com/pyodide/pyodide/releases/download/"
    f"{PYODIDE_VERSION}/pyodide-{PYODIDE_VERSION}.tar.bz2"
)
SERVER_ONLY = {"uvicorn", "click"}  # the phone app has no web server of its own
BACKEND = Path(__file__).resolve().parents[2] / "backend"


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pyodide = out / "pyodide"
    if not (pyodide / "pyodide-lock.json").is_file():
        archive = out / "pyodide.tar.bz2"
        if not archive.is_file():
            print(f"downloading Pyodide {PYODIDE_VERSION}")
            urllib.request.urlretrieve(PYODIDE_URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(out, filter="data")
        archive.unlink()
    lock = json.loads((pyodide / "pyodide-lock.json").read_text())
    provided = {norm(k) for k in lock["packages"]}

    reqs = subprocess.run(
        ["uv", "export", "--no-hashes", "--no-dev", "--no-emit-project", "--frozen"],
        cwd=BACKEND, check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    pins = []
    for line in reqs.splitlines():
        line = line.split(";")[0].strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name = line.split("==")[0]
        if norm(name) in provided or norm(name) in SERVER_ONLY:
            continue
        pins.append(line)

    wheels = out / "wheels"
    wheels.mkdir(exist_ok=True)
    for old in wheels.glob("*.whl"):
        old.unlink()
    subprocess.run(
        [sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary", ":all:",
         "--platform", "any", "--implementation", "py", "--python-version", "3.14",
         "-d", str(wheels), *pins],
        check=True,
    )  # fmt: skip
    subprocess.run(["uv", "build", "--wheel", "-o", str(wheels)], cwd=BACKEND, check=True)
    names = sorted(p.name for p in wheels.glob("*.whl"))
    print(f"{len(names)} wheels: " + ", ".join(names))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
