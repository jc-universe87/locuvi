"""Disposable local WebDAV server (WsgiDAV) — never a live Nextcloud."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from cheroot import wsgi
from wsgidav.wsgidav_app import WsgiDAVApp

USER = "alex"
PASSWORD = "fixture-app-password"
DAV_PREFIX = f"/remote.php/dav/files/{USER}"


class DavServer:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        config = {
            "host": "127.0.0.1",
            "port": 0,
            "provider_mapping": {DAV_PREFIX: str(root)},
            "simple_dc": {"user_mapping": {"*": {USER: {"password": PASSWORD}}}},
            "http_authenticator": {
                "domain_controller": None,
                "accept_basic": True,
                "accept_digest": False,
                "default_to_digest": False,
            },
            "verbose": 0,
            "logging": {"enable": False},
            "property_manager": True,
            "lock_storage": True,
        }
        logging.getLogger("wsgidav").setLevel(logging.ERROR)
        self.app = WsgiDAVApp(config)
        self.server = wsgi.Server(("127.0.0.1", 0), self.app)
        self.server.prepare()
        self.port = self.server.bind_addr[1]
        self.thread = threading.Thread(target=self.server.serve, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{DAV_PREFIX}/"

    def stop(self) -> None:
        self.server.stop()
