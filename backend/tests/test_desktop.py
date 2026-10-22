"""The Windows/macOS app's sign-in link and phone access setting. Fictional data only."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from locuvi import desktop
from locuvi.main import create_app


def _client(settings, tmp_path, **kw):
    st = replace(settings, auth_mode="password", password="random-bootstrap-0000",
                 desktop=True, desktop_token="launch-token-0000",
                 desktop_config=tmp_path / "desktop.json", **kw)  # fmt: skip
    return TestClient(create_app(st))


def test_window_signs_in_with_the_launch_token_only(settings, tmp_path):
    with _client(settings, tmp_path) as c:
        assert c.get("/api/v1/auth/session").json()["authenticated"] is False
        wrong = c.get("/desktop/open?token=nope", follow_redirects=False)
        assert wrong.status_code == 303 and "set-cookie" not in wrong.headers
        assert c.get("/api/v1/auth/session").json()["authenticated"] is False
        ok = c.get("/desktop/open?token=launch-token-0000", follow_redirects=False)
        assert ok.status_code == 303 and ok.headers["location"] == "/"
        assert c.get("/api/v1/auth/session").json()["authenticated"] is True


def test_link_does_nothing_on_a_server(settings, tmp_path):
    st = replace(settings, auth_mode="password", password="pw-0000", desktop_token="t")
    with TestClient(create_app(st)) as c:
        c.get("/desktop/open?token=t")
        assert c.get("/api/v1/auth/session").json()["authenticated"] is False
        c.post("/api/v1/auth/login", json={"password": "pw-0000"})
        assert c.get("/api/v1/desktop").json() == {"available": False}


def test_phone_access_needs_own_password_and_a_restart(settings, tmp_path, monkeypatch):
    monkeypatch.delenv("LOCUVI_DESKTOP_HOST", raising=False)
    with _client(settings, tmp_path) as c:
        c.get("/desktop/open?token=launch-token-0000")
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        st = c.get("/api/v1/desktop").json()
        assert st["available"] and not st["phone_access"] and not st["own_password"]
        refused = c.put("/api/v1/desktop", headers=h, json={"phone_access": True})
        assert refused.json()["error"]["code"] == "desktop.set_password_first"
        new = {"current": "random-bootstrap-0000", "new": "my-own-password-0000"}
        r = c.post("/api/v1/auth/password", headers=h, json=new)
        h = {"X-CSRF-Token": r.json()["csrf_token"]}
        on = c.put("/api/v1/desktop", headers=h, json={"phone_access": True}).json()
        assert on["phone_access"] and on["restart_needed"] and on["own_password"]
        assert desktop.read_config(tmp_path / "desktop.json")["phone_access"] is True
        # after the restart the app listens on the network and lists its addresses
        monkeypatch.setenv("LOCUVI_DESKTOP_HOST", "0.0.0.0")
        monkeypatch.setenv("LOCUVI_DESKTOP_PORT", "8765")
        monkeypatch.setattr(desktop, "local_addresses", lambda: ["192.0.2.10"])
        now = c.get("/api/v1/desktop").json()
        assert not now["restart_needed"] and now["addresses"] == ["http://192.0.2.10:8765"]


def test_config_file_defaults_and_bad_values(tmp_path):
    assert desktop.read_config(None) == {"phone_access": False, "port": 8765}
    p = tmp_path / "d.json"
    p.write_text("not json")
    assert desktop.read_config(p)["phone_access"] is False
    desktop.write_config(p, {"phone_access": True, "port": 80})
    assert desktop.read_config(p) == {"phone_access": True, "port": 8765}


def test_web_files_get_the_right_type_even_when_the_system_list_is_wrong(settings, tmp_path):
    """Windows often maps .js to text/plain; browsers then refuse to run Locuvi at all."""
    import mimetypes

    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / "assets" / "app.js").write_text("export {}")
    (static / "manifest.webmanifest").write_text("{}")
    mimetypes.add_type("text/plain", ".js")  # what a broken registry does
    with TestClient(create_app(replace(settings, static_dir=static))) as c:
        assert c.get("/assets/app.js").headers["content-type"].startswith("text/javascript")
        manifest = c.get("/manifest.webmanifest").headers["content-type"]
        assert manifest.startswith("application/manifest+json")
