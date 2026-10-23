"""The desktop app stops by itself once its window is closed (locuvi.desktop.should_stop)."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from locuvi import desktop
from locuvi.main import create_app


def test_stops_after_the_window_goes_quiet():
    desktop.reset()
    assert not desktop.should_stop(now=60, started=0, phone_access=False)  # window opening
    assert desktop.should_stop(now=desktop.FIRST_SECONDS + 1, started=0, phone_access=False)
    desktop.seen(100)
    assert not desktop.should_stop(
        now=100 + desktop.IDLE_SECONDS - 1, started=0, phone_access=False
    )
    assert desktop.should_stop(now=100 + desktop.IDLE_SECONDS + 1, started=0, phone_access=False)
    # phones still need it
    assert not desktop.should_stop(now=10_000, started=0, phone_access=True)
    desktop.ask_to_quit()
    assert desktop.should_stop(now=101, started=0, phone_access=True)
    desktop.reset()


def test_window_keeps_it_alive_and_quit_stops_it(settings, tmp_path):
    desktop.reset()
    st = replace(settings, auth_mode="password", password="random-bootstrap-0000", desktop=True,
                 desktop_token="t-0000", desktop_config=tmp_path / "desktop.json")  # fmt: skip
    with TestClient(create_app(st)) as c:
        c.get("/desktop/open?token=t-0000")
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert c.post("/api/v1/desktop/alive", headers=h).json() == {"ok": True}
        assert desktop._state["last_seen"] is not None
        assert not desktop._state["quit"]
        assert c.post("/api/v1/desktop/quit", headers=h).json() == {"ok": True}
        assert desktop._state["quit"]
    desktop.reset()


def test_not_on_a_server(settings):
    st = replace(settings, auth_mode="password", password="pw-0000")
    with TestClient(create_app(st)) as c:
        c.post("/api/v1/auth/login", json={"password": "pw-0000"})
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert c.post("/api/v1/desktop/quit", headers=h).status_code == 404
    assert not desktop._state["quit"]
