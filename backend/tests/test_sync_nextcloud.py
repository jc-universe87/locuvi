"""Sync through Nextcloud (WebDAV): two addresses, and the phone's way of connecting.

Only against a disposable local WebDAV server (webdav_fixture), never a live Nextcloud.
Fictional data only."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from test_sync_engine import Device
from webdav_fixture import PASSWORD, USER, DavServer

from locuvi.config import WebDavAllowlist
from locuvi.errors import DomainError
from locuvi.models import Practice
from locuvi.sync import engine
from locuvi.webdav import browser
from locuvi.webdav.urlguard import UrlBlocked, validate_base_url


@pytest.fixture
def dav(tmp_path):
    srv = DavServer(tmp_path / "davroot")
    yield srv
    srv.stop()


def device(tmp_path, name: str) -> Device:
    d = Device(tmp_path, name)
    d.settings = replace(
        d.settings,
        webdav_allowlist=WebDavAllowlist.parse("127.0.0.1"),  # the test server is local
        webdav_allow_http_for_allowlisted=True,
    )
    return d


def spec(d: Device, url: str, home_url: str | None = None, password: str = PASSWORD):
    return engine.nextcloud_spec(
        d.settings, d.secrets, url=url, home_url=home_url, username=USER, password=password
    )


def test_two_devices_sync_through_nextcloud(tmp_path, dav):
    laptop, phone = device(tmp_path, "laptop"), device(tmp_path, "phone")
    with laptop.session() as s:
        s.add(Practice(id="p1", name="Example Surgery"))
        s.commit()
    code = engine.start(laptop.settings, laptop.secrets, spec(laptop, dav.base_url), "Laptop")
    assert (tmp_path / "davroot" / "Locuvi" / "Locuvi Sync" / "state.lcv").is_file()

    engine.join(phone.settings, phone.secrets, spec(phone, dav.base_url), "Phone", code)
    with phone.session() as s:
        assert s.get(Practice, "p1").name == "Example Surgery"
        s.add(Practice(id="p2", name="Example Health Centre"))
        s.commit()
    # the phone adopted the household key: its saved app password must still open
    phone.sync()
    laptop.sync()
    with laptop.session() as s:
        assert s.get(Practice, "p2") is not None

    st = engine.status(phone.settings)
    assert st["nextcloud"]["url"] == dav.base_url and st["nextcloud"]["username"] == USER
    assert (
        PASSWORD not in str(st)
        and PASSWORD not in (phone.settings.data_dir / "sync" / "config.json").read_text()
    )


def test_the_address_that_answers_is_used(tmp_path, dav):
    laptop = device(tmp_path, "laptop")
    dead = "http://127.0.0.1:9/remote.php/dav/files/alex/"  # nothing listens there
    engine.start(laptop.settings, laptop.secrets, spec(laptop, dead, dav.base_url), "Laptop")
    assert engine.status(laptop.settings)["nextcloud"]["reached"] == "home_url"
    laptop.sync()  # and the next sync tries that one first
    assert engine.status(laptop.settings)["nextcloud"]["reached"] == "home_url"


def test_wrong_app_password_says_so(tmp_path, dav):
    laptop = device(tmp_path, "laptop")
    with pytest.raises(DomainError) as e:
        bad = spec(laptop, dav.base_url, password="nope")
        engine.start(laptop.settings, laptop.secrets, bad, "Laptop")
    assert e.value.code == "sync.webdav_auth_rejected"
    assert "app password" in e.value.message
    assert not engine.load_config(laptop.settings).enabled


def test_plain_server_address_becomes_the_webdav_address(tmp_path):
    d = device(tmp_path, "laptop")
    s = engine.nextcloud_spec(
        d.settings, d.secrets, url="cloud.example.invalid", home_url=None,
        username="alex example", password="x",
    )  # fmt: skip
    assert s["url"] == "https://cloud.example.invalid/remote.php/dav/files/alex%20example/"
    full = "https://cloud.example.invalid/remote.php/dav/files/alex/Shared/"
    assert engine.nextcloud_spec(
        d.settings, d.secrets, url=full, home_url=None, username="alex", password="x"
    )["url"] == full  # fmt: skip
    with pytest.raises(DomainError) as e:
        engine.nextcloud_spec(
            d.settings, d.secrets, url="http://cloud.example.invalid", home_url=None,
            username="alex", password="x",
        )  # fmt: skip
    assert e.value.code == "sync.nextcloud_url"


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.20/remote.php/dav/files/a/",
        "https://10.0.0.5:8443/",
        "http://nas.local/",
        "http://nextcloud/",
        "https://100.101.102.103/",  # Tailscale
        "http://[fd12:3456::1]/",
    ],
)
def test_home_network_address_may_be_private(settings, url):
    assert validate_base_url(url, settings, home=True).home
    with pytest.raises(UrlBlocked):
        validate_base_url(url, settings)  # but not as the usual address


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/",  # cloud metadata
        "http://metadata.google.internal/",
        "http://cloud.example.invalid/",  # a public name still needs https
    ],
)
def test_home_network_address_still_blocks_special_ones(settings, url):
    with pytest.raises(UrlBlocked):
        validate_base_url(url, settings, home=True)


# ------------------------------------------------------------------ the phone's connection


class FakeWorker:
    """Stands in for locuviNet in the phone app's Web Worker: makes the request (as the
    Android app or the browser would) and answers in the same shape."""

    def __init__(self, hide: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.seen: list[tuple[str, list[str]]] = []
        self.hide = hide  # response headers the browser keeps from the page (CORS)

    def __call__(self, method, url, headers_json, body, timeout_ms):  # type: ignore[no-untyped-def]
        import json

        headers = json.loads(headers_json)
        self.seen.append((method, [k.lower() for k, _ in headers]))
        try:
            r = httpx.request(method, url, headers=headers, content=body, timeout=timeout_ms / 1000)
        except httpx.TimeoutException:
            return {"error": "timeout"}
        except httpx.TransportError:
            return {"error": "unreachable"}
        shown = [(k, v) for k, v in r.headers.items() if k.lower() not in self.hide]
        return {"status": r.status_code, "headers": json.dumps(shown),
                "body": r.content}  # fmt: skip


def test_phone_syncs_through_the_app_or_browser(tmp_path, dav, monkeypatch):
    laptop = device(tmp_path, "laptop")
    code = engine.start(laptop.settings, laptop.secrets, spec(laptop, dav.base_url), "Laptop")

    worker = FakeWorker()
    monkeypatch.setenv("LOCUVI_POCKET", "1")
    monkeypatch.setattr(browser.BrowserTransport, "_call", lambda self: worker)
    phone = device(tmp_path, "phone")
    dead = "http://127.0.0.1:9/"
    engine.join(phone.settings, phone.secrets, spec(phone, dead, dav.base_url), "Phone", code)
    assert engine.status(phone.settings)["nextcloud"]["reached"] == "home_url"
    with phone.session() as s:
        s.add(Practice(id="p2", name="Example Health Centre"))
        s.commit()
    phone.sync()
    laptop.sync()
    with laptop.session() as s:
        assert s.get(Practice, "p2") is not None
    methods = {m for m, _ in worker.seen}
    assert {"OPTIONS", "GET", "PUT", "PROPFIND", "MKCOL"} <= methods
    # only headers a page may set: the browser adds the rest itself
    sent = {h for _, hs in worker.seen for h in hs}
    assert "authorization" in sent and not sent & {"host", "content-length", "user-agent"}


def test_phone_explains_when_nextcloud_cant_be_reached(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCUVI_POCKET", "1")
    monkeypatch.setattr(browser.BrowserTransport, "_call", lambda self: FakeWorker())
    phone = device(tmp_path, "phone")
    with pytest.raises(DomainError) as e:
        engine.join(phone.settings, phone.secrets, spec(phone, "http://127.0.0.1:9/"),
                    "Phone", "ABCD-EFGH-JKMN-PQRS-TUVW")  # fmt: skip
    assert e.value.code == "sync.webdav_unreachable"
    assert "iPhone" in e.value.message


def test_phone_never_overwrites_when_the_browser_hides_etag(tmp_path, dav, monkeypatch):
    """A Nextcloud that allows Locuvi but doesn't expose ETag: versions come from listings."""
    laptop = device(tmp_path, "laptop")
    code = engine.start(laptop.settings, laptop.secrets, spec(laptop, dav.base_url), "Laptop")
    monkeypatch.setenv("LOCUVI_POCKET", "1")
    monkeypatch.setattr(browser.BrowserTransport, "_call", lambda self: FakeWorker({"etag"}))
    phone = device(tmp_path, "phone")
    engine.join(phone.settings, phone.secrets, spec(phone, dav.base_url), "Phone", code)
    with phone.session() as s:
        s.add(Practice(id="p2", name="Example Health Centre"))
        s.commit()
    assert phone.sync().pushed
    monkeypatch.delenv("LOCUVI_POCKET")
    with laptop.session() as s:
        s.add(Practice(id="p3", name="Example Clinic"))
        s.commit()
    laptop.sync()
    monkeypatch.setenv("LOCUVI_POCKET", "1")
    phone.sync()  # merges the laptop's change rather than writing over it
    with phone.session() as s:
        assert s.get(Practice, "p3") is not None
    monkeypatch.delenv("LOCUVI_POCKET")
    laptop.sync()
    with laptop.session() as s:
        assert s.get(Practice, "p2") is not None
