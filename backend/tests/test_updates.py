"""New versions of the Windows and Mac app (locuvi.updates). No real network: GitHub is faked."""

from __future__ import annotations

import hashlib
import sys
import types

import httpx
import pytest

from locuvi import updates
from locuvi.errors import DomainError

INSTALLER = b"MZ fictional installer bytes"


def fake_github(version: str = "v1.1.20", data: bytes = INSTALLER, digest: str | None = None):
    name = updates.ASSETS.get(sys.platform, "Locuvi-Windows-Setup.exe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={
                "tag_name": version,
                "html_url": "https://github.com/jc-universe87/locuvi/releases/tag/" + version,
                "assets": [{
                    "name": name, "size": len(data),
                    "digest": "sha256:" + (digest or hashlib.sha256(data).hexdigest()),
                    "browser_download_url": "https://github.com/download/" + name,
                }],
            })  # fmt: skip
        if request.url.path.startswith("/download/"):
            return httpx.Response(200, content=data)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def released(monkeypatch):
    """Pretend to be the Windows app, released as 1.1.16."""
    monkeypatch.setitem(sys.modules, "locuvi._release", types.SimpleNamespace(VERSION="1.1.16"))
    monkeypatch.setattr(sys, "platform", "win32")
    updates._cache.update(at=0.0, info=None)
    yield
    updates._cache.update(at=0.0, info=None)


def test_versions_compare_by_number():
    assert updates.parse("v1.1.16") < updates.parse("1.1.17") < updates.parse("1.2")
    assert updates.parse("1.1.10") > updates.parse("1.1.9")
    assert updates.parse("nonsense") == ()


def test_not_a_released_app_never_checks(monkeypatch):
    monkeypatch.setitem(sys.modules, "locuvi._release", None)  # import fails: built from code
    assert updates.check(force=True) == {
        "supported": False, "current": None, "latest": None, "available": False
    }  # fmt: skip


def test_newer_release_is_offered_and_checked_rarely(released):
    gh = fake_github()
    st = updates.check(client=gh)
    assert st["available"] and st["latest"] == "1.1.20" and st["current"] == "1.1.16"
    calls = []
    seen = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))
    gh2 = httpx.Client(transport=seen)
    assert updates.check(client=gh2)["available"]  # from the last check: no new request
    assert calls == []


def test_same_version_is_not_an_update(released):
    assert not updates.check(force=True, client=fake_github("v1.1.16"))["available"]


def test_offline_check_never_asks_github(released):
    gh = httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("asked GitHub")))
    assert updates.check(offline=True, client=gh)["available"] is False


def test_download_is_checked_against_the_release(released, tmp_path):
    updates.check(force=True, client=fake_github())
    f = updates.download(tmp_path, client=fake_github())
    assert f.read_bytes() == INSTALLER

    updates.check(force=True, client=fake_github(digest="0" * 64))
    with pytest.raises(DomainError) as e:
        updates.download(tmp_path / "bad", client=fake_github(digest="0" * 64))
    assert e.value.code == "updates.bad_file"
    assert not list((tmp_path / "bad").glob("*"))  # nothing half-downloaded is kept


def test_install_waits_for_locuvi_then_reopens_it(released, tmp_path):
    cmd = " ".join(updates.install_command(tmp_path / "setup.exe", tmp_path / "app", 4242))
    assert "Wait-Process -Id 4242" in cmd and "/VERYSILENT" in cmd and "Locuvi.exe" in cmd


def test_mac_install_replaces_the_app_and_keeps_the_old_one_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    cmd = updates.install_command(tmp_path / "Locuvi-macOS.dmg", tmp_path / "Locuvi.app", 7)[-1]
    assert "kill -0 7" in cmd and "ditto" in cmd and 'open "' in cmd
    assert 'mv "' + str(tmp_path / "Locuvi.app") + '.old" "' in cmd  # put back if copy failed


def test_server_has_no_updates(settings):
    from test_api import client_for

    with client_for(settings) as c:
        assert c.get("/api/v1/updates").json() == {"supported": False}
