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
    updates._cache.update(at=0.0, info=None, file=None, installing=False)
    yield
    updates._cache.update(at=0.0, info=None, file=None, installing=False)


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
    folder = tmp_path / "Jo O'Brien" / "updates"  # spaces and an apostrophe in the path
    folder.mkdir(parents=True)
    cmd = updates.install_command(folder / "setup.exe", tmp_path / "app", 4242)
    assert cmd[0] == "powershell" and cmd[-1] == str(folder / "update.ps1")
    script = (folder / "update.ps1").read_text(encoding="utf-8-sig")
    assert "Wait-Process -Id 4242" in script and "/VERYSILENT" in script
    assert "Jo O''Brien" in script  # quoted for PowerShell
    assert script.index("Start-Process -Wait") < script.index("Locuvi.exe")


def test_found_update_is_downloaded_once_in_the_background(released, tmp_path):
    assert updates.prepare(tmp_path, client=fake_github())
    f = updates.ready_file()
    assert f is not None and f.read_bytes() == INSTALLER
    gh = httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("downloaded again")))
    assert updates.prepare(tmp_path, client=gh)


def test_nothing_new_nothing_downloaded(released, tmp_path):
    assert not updates.prepare(tmp_path, client=fake_github("v1.1.16"))
    assert updates.ready_file() is None and not list(tmp_path.glob("*"))


def test_closing_locuvi_installs_the_ready_update_and_leaves_it_closed(
    released, tmp_path, monkeypatch
):
    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(updates, "app_bundle", lambda: tmp_path / "app")
    assert not updates.install_on_exit()  # nothing downloaded yet: closes as usual
    updates.prepare(tmp_path / "updates", client=fake_github())
    assert updates.install_on_exit()
    script = (tmp_path / "updates" / "update.ps1").read_text(encoding="utf-8-sig")
    assert "/VERYSILENT" in script and "update-done" in script
    assert "Locuvi.exe" not in script  # stays closed: it's new the next time it's opened
    assert len(started) == 1
    assert not updates.install_on_exit()  # once is enough


def test_running_for_phones_installs_with_no_window_open_at_night(released, tmp_path):
    cmd = updates.install_command(tmp_path / "setup.exe", tmp_path / "app", 1, ["--no-window"])
    script = (tmp_path / "update.ps1").read_text(encoding="utf-8-sig")
    assert cmd[0] == "powershell" and "-ArgumentList @('--no-window')" in script
    assert updates.due_while_running(45 * 60, 3)
    assert not updates.due_while_running(45 * 60, 14)  # daytime: wait
    assert not updates.due_while_running(5 * 60, 3)  # someone used it just now
    assert not updates.due_while_running(None, 3)


def test_mac_install_replaces_the_app_and_keeps_the_old_one_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    cmd = updates.install_command(tmp_path / "Locuvi-macOS.dmg", tmp_path / "Locuvi.app", 7)[-1]
    assert "kill -0 7" in cmd and "ditto" in cmd and 'open "' in cmd
    assert 'mv "' + str(tmp_path / "Locuvi.app") + '.old" "' in cmd  # put back if copy failed
    quiet = updates.install_command(tmp_path / "L.dmg", tmp_path / "Locuvi.app", 7, None)[-1]
    assert "update-done" in quiet and 'open "' not in quiet
    bg = updates.install_command(tmp_path / "L.dmg", tmp_path / "Locuvi.app", 7, ["--no-window"])
    assert '--args "--no-window"' in bg[-1]


def test_server_has_no_updates(settings):
    from test_api import client_for

    with client_for(settings) as c:
        assert c.get("/api/v1/updates").json() == {"supported": False}


def test_reopened_locuvi_starts_with_a_clean_environment(monkeypatch):
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/old")
    monkeypatch.setenv("LOCUVI_DESKTOP_TOKEN", "secret-launch-token")
    monkeypatch.setenv("DATA_DIR", "/tmp/old")
    env = updates.clean_environment()
    assert "_PYI_APPLICATION_HOME_DIR" not in env and "DATA_DIR" not in env
    assert "LOCUVI_DESKTOP_TOKEN" not in env and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env.get("PATH") == __import__("os").environ.get("PATH")
