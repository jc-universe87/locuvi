"""A stand-in Nextcloud for the sync tests: a disposable WebDAV folder, never a real server.

    uv run python ../e2e/fake_nextcloud.py --root DIR --http 8791 --https 8792 \
        --allow-origin http://127.0.0.1:8790

Serves the same files under /remote.php/dav/files/alex/ (user "alex", app password
"fixture-app-password") over http:// (for a computer, as a home network address) and, with
--https, over https:// with a self-signed certificate made on the spot.

Browsers only let a page from another address use it if it allows that address (CORS). With
--allow-origin it answers as docs/SYNC.md tells a Nextcloud owner to set theirs up; without,
it sends no CORS headers at all, like a Nextcloud nobody changed.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import tempfile
import threading
from pathlib import Path

from cheroot import wsgi
from cheroot.ssl.builtin import BuiltinSSLAdapter
from wsgidav.wsgidav_app import WsgiDAVApp

USER, PASSWORD = "alex", "fixture-app-password"
METHODS = "GET, PUT, DELETE, MKCOL, MOVE, COPY, PROPFIND, OPTIONS"
HEADERS = "Authorization, Content-Type, Depth, Destination, Overwrite, If-Match, If-None-Match"


def cors(app, origins: set[str]):  # type: ignore[no-untyped-def]
    def wrapped(environ, start_response):  # type: ignore[no-untyped-def]
        origin = environ.get("HTTP_ORIGIN")
        if not origin or origin not in origins:
            return app(environ, start_response)
        allow = [
            ("Access-Control-Allow-Origin", origin),
            ("Access-Control-Expose-Headers", "ETag"),
            ("Vary", "Origin"),
        ]
        if environ["REQUEST_METHOD"] == "OPTIONS" and environ.get(
            "HTTP_ACCESS_CONTROL_REQUEST_METHOD"
        ):
            start_response("204 No Content", [
                *allow,
                ("Access-Control-Allow-Methods", METHODS),
                ("Access-Control-Allow-Headers", HEADERS),
                ("Access-Control-Max-Age", "600"),
            ])  # fmt: skip
            return [b""]

        def start(status, headers, exc_info=None):  # type: ignore[no-untyped-def]
            return start_response(status, [*headers, *allow], exc_info)

        return app(environ, start)

    return wrapped


def self_signed(folder: Path) -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nextcloud.example.invalid")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("nextcloud.example.invalid")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    c, k = folder / "cert.pem", folder / "key.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))  # fmt: skip
    return str(c), str(k)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--http", type=int, required=True)
    ap.add_argument("--https", type=int)
    ap.add_argument("--allow-origin", action="append", default=[])
    a = ap.parse_args()
    root = Path(a.root)
    root.mkdir(parents=True, exist_ok=True)
    logging.getLogger("wsgidav").setLevel(logging.ERROR)
    dav = WsgiDAVApp({
        "host": a.host, "port": a.http,
        "provider_mapping": {f"/remote.php/dav/files/{USER}": str(root)},
        "simple_dc": {"user_mapping": {"*": {USER: {"password": PASSWORD}}}},
        "http_authenticator": {"domain_controller": None, "accept_basic": True,
                               "accept_digest": False, "default_to_digest": False},
        "verbose": 0, "logging": {"enable": False},
        "property_manager": True, "lock_storage": True,
    })  # fmt: skip
    app = cors(dav, set(a.allow_origin))
    servers = [wsgi.Server((a.host, a.http), app)]
    if a.https:
        tls = wsgi.Server((a.host, a.https), app)
        tls.ssl_adapter = BuiltinSSLAdapter(*self_signed(Path(tempfile.mkdtemp())))
        servers.append(tls)
    for s in servers[1:]:
        threading.Thread(target=s.safe_start, daemon=True).start()
    print(f"fake Nextcloud on :{a.http}" + (f" and https :{a.https}" if a.https else ""), flush=True)
    servers[0].safe_start()


if __name__ == "__main__":
    main()
