"""Household profiles: separate data per person, admin-managed, password protected.

Fictional data only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from locuvi import profiles
from locuvi.config import Settings
from locuvi.main import create_app

PRACTICE = {"name": "Example Medical Practice", "billing_address": "2 Test Road"}


@pytest.fixture
def st(tmp_path):
    return Settings(
        app_env="test",
        data_dir=tmp_path / "d",
        key_dir=tmp_path / "k",
        auth_mode="password",
        password="file-password-1",
        cookie_secure=False,
        worker_enabled=False,
    )


def login(c, password, name=None):
    body = {"password": password} | ({"name": name} if name else {})
    r = c.post("/api/v1/auth/login", json=body)
    return r


def csrf(c):
    return {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}


def test_admin_from_existing_install_and_separate_data(st):
    app = create_app(st)
    with TestClient(app) as admin:
        # the existing owner becomes profile 1, admin, with the secret-file password
        assert login(admin, "file-password-1").status_code == 200
        me = admin.get("/api/v1/auth/session").json()
        assert me["profile"]["is_admin"] and me["profile"]["id"] == 1 and not me["multi"]
        h = csrf(admin)
        assert admin.post("/api/v1/practices", json=PRACTICE, headers=h).status_code in (200, 201)

        r = admin.post("/api/v1/profiles", headers=h,
                       json={"name": "Sam", "password": "sam-password-1"})  # fmt: skip
        assert r.status_code == 201 and r.json()["is_admin"] is False
        sam_id = r.json()["id"]
        assert (st.data_dir / "profiles" / str(sam_id) / "locuvi.db").is_file()
        dup = admin.post("/api/v1/profiles", headers=h,
                         json={"name": "sam", "password": "another-pass-1"})  # fmt: skip
        assert dup.status_code == 400 and dup.json()["error"]["code"] == "profile.name_taken"

        sam = TestClient(app)
        # with two profiles the sign-in needs a name
        assert sam.get("/api/v1/auth/session").json()["multi"] is True
        assert login(sam, "sam-password-1").status_code == 401
        assert login(sam, "sam-password-1", "Owner").status_code == 401
        r = login(sam, "sam-password-1", "  sam ")
        assert r.status_code == 200 and r.json()["profile"]["name"] == "Sam"
        hs = csrf(sam)
        # Sam starts empty and never sees the admin's practices, and vice versa
        assert sam.get("/api/v1/practices").json() == []
        sam.post("/api/v1/practices", headers=hs, json={**PRACTICE, "name": "Sam's Surgery"})
        assert [p["name"] for p in sam.get("/api/v1/practices").json()] == ["Sam's Surgery"]
        assert [p["name"] for p in admin.get("/api/v1/practices").json()] == [PRACTICE["name"]]
        # only the admin manages profiles
        assert sam.get("/api/v1/profiles").status_code == 403
        eve = {"name": "Eve", "password": "eve-password-1"}
        assert sam.post("/api/v1/profiles", headers=hs, json=eve).status_code == 403

    # after a restart every profile's data is still there
    with TestClient(create_app(st)) as again:
        assert login(again, "sam-password-1", "Sam").status_code == 200
        assert [p["name"] for p in again.get("/api/v1/practices").json()] == ["Sam's Surgery"]


def test_reset_remove_restore_and_purge(st):
    app = create_app(st)
    with TestClient(app) as admin:
        login(admin, "file-password-1")
        h = csrf(admin)
        new = {"name": "Sam", "password": "sam-password-1"}
        sid = admin.post("/api/v1/profiles", headers=h, json=new).json()["id"]
        sam = TestClient(app)
        login(sam, "sam-password-1", "Sam")
        assert sam.get("/api/v1/practices").status_code == 200

        # the admin sets a new password: Sam is signed out everywhere
        r = admin.patch(f"/api/v1/profiles/{sid}", headers=h, json={"password": "new-sam-pass-2"})
        assert r.status_code == 200
        assert sam.get("/api/v1/practices").status_code == 401
        assert login(sam, "sam-password-1", "Sam").status_code == 401
        assert login(sam, "new-sam-pass-2", "Sam").status_code == 200
        short = admin.patch(f"/api/v1/profiles/{sid}", headers=h, json={"password": "short"})
        assert short.status_code == 422

        # Sam changes their own password
        r = sam.post("/api/v1/auth/password", headers=csrf(sam),
                     json={"current": "new-sam-pass-2", "new": "sams-own-pass-3"})  # fmt: skip
        assert r.status_code == 200
        assert login(TestClient(app), "sams-own-pass-3", "Sam").status_code == 200

        # removing signs Sam out and keeps the data aside; restore brings it back
        assert admin.delete("/api/v1/profiles/1", headers=h).status_code == 400  # not the admin
        assert admin.delete(f"/api/v1/profiles/{sid}", headers=h).status_code == 200
        assert sam.get("/api/v1/practices").status_code == 401
        assert login(TestClient(app), "sams-own-pass-3", "Sam").status_code == 401
        listed = admin.get("/api/v1/profiles").json()
        assert [p["name"] for p in listed["removed"]] == ["Sam"]
        assert admin.post(f"/api/v1/profiles/{sid}/restore", headers=h).status_code == 200
        assert login(TestClient(app), "sams-own-pass-3", "Sam").status_code == 200

        # removed for more than 30 days: the data is deleted for good
        admin.delete(f"/api/v1/profiles/{sid}", headers=h)
        folder = profiles.data_dir(st, sid)
        assert folder.is_dir()
        assert profiles.purge_removed(st) == []
        later = datetime.now(UTC) + timedelta(days=31)
        assert profiles.purge_removed(st, now=later) == [sid]
        assert not folder.exists()
        assert admin.post(f"/api/v1/profiles/{sid}/restore", headers=h).status_code == 400


def test_links_and_tokens_find_their_profile(st):
    app = create_app(st)
    with TestClient(app) as admin:
        login(admin, "file-password-1")
        admin.post("/api/v1/profiles", headers=csrf(admin),
                   json={"name": "Sam", "password": "sam-password-1"})  # fmt: skip
        sam = TestClient(app)
        login(sam, "sam-password-1", "Sam")
        hs = csrf(sam)
        sam.post("/api/v1/practices", headers=hs, json={**PRACTICE, "name": "Sam's Surgery"})

        # Sam's Bevro token reads Sam's data only
        tok = sam.post("/api/v1/settings/agents", headers=hs,
                       json={"name": "Bevro", "allow_drafts": False}).json()["token"]  # fmt: skip
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "list_practices", "arguments": {}}}  # fmt: skip
        r = TestClient(app).post("/mcp", content=json.dumps(rpc),
                                 headers={"Authorization": f"Bearer {tok}",
                                          "Content-Type": "application/json"})  # fmt: skip
        assert r.status_code == 200
        text = json.dumps(r.json())
        assert "Sam's Surgery" in text and "Example Medical Practice" not in text

        # Sam's calendar link serves Sam's diary
        cal = sam.put("/api/v1/settings/calendar", headers=hs, json={"enabled": True}).json()
        url = cal.get("url") or cal.get("path") or ""
        token = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".ics")
        assert token
        assert TestClient(app).get(f"/calendar/{token}.ics").status_code == 200
        assert TestClient(app).get("/calendar/nope.ics").status_code == 404


def test_cli_reset_password_for_a_profile(st):
    from locuvi import cli

    app = create_app(st)
    with TestClient(app) as admin:
        login(admin, "file-password-1")
        h = csrf(admin)
        admin.post("/api/v1/profiles", headers=h,
                   json={"name": "Sam", "password": "sam-password-1"})  # fmt: skip
        admin.post("/api/v1/auth/password", headers=h,
                   json={"current": "file-password-1", "new": "admin-new-pass-1"})  # fmt: skip
    cli.reset_password(st, "Sam")
    cli.reset_password(st)
    with TestClient(create_app(st)) as c:
        assert login(c, "file-password-1", "Sam").status_code == 200
        assert login(TestClient(c.app), "file-password-1", "Owner").status_code == 200


def test_profile_list_is_backed_up(st, tmp_path):
    from dataclasses import replace

    st = replace(st, backup_dir=tmp_path / "b")
    with TestClient(create_app(st)) as admin:
        login(admin, "file-password-1")
        admin.post("/api/v1/profiles", headers=csrf(admin),
                   json={"name": "Sam", "password": "sam-password-1"})  # fmt: skip
    dest = profiles.backup_registry(st)
    assert dest == st.backup_dir / "profiles.db"
    import sqlite3

    names = [r[0] for r in sqlite3.connect(dest).execute("SELECT name FROM profile ORDER BY id")]
    assert names == ["Owner", "Sam"]


def test_login_burst_cannot_bypass_the_limit(st):
    """Attempts are reserved before the slow password check, so parallel guesses count."""
    import threading

    app = create_app(st)
    with TestClient(app):
        sm = app.state.sessions
        results: list[object] = []

        def guess():
            try:
                results.append(sm.check_password(None, "wrong-password"))
            except Exception as exc:  # noqa: BLE001
                results.append(type(exc).__name__)

        threads = [threading.Thread(target=guess) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count(None) == 5 and results.count("TooManyAttempts") == 7


def test_upgrade_keeps_the_old_session_epoch(st):
    """Sessions a past password change ended must not come back when profiles arrive."""
    from locuvi import db
    from locuvi.api.auth import hash_password
    from locuvi.migrate import upgrade
    from locuvi.models import AuthConfig

    eng = db.init_engine(st.db_path)
    upgrade(eng)
    with db.new_session() as s:
        s.add(AuthConfig(id=1, password_hash=hash_password("changed-password-1"), session_epoch=3))
        s.commit()
    eng.dispose()
    with TestClient(create_app(st)):
        admin = profiles.get(st, 1)
        assert admin is not None and admin.session_epoch == 3


def test_offsite_backups_are_kept_apart(st):
    other = profiles.settings_for(st, 7)
    assert other.backup_remote_path == f"{st.backup_remote_path}/profile-7"
    assert profiles.settings_for(st, 1).backup_remote_path == st.backup_remote_path


def test_purge_retries_and_never_removes_a_restored_profile(st, monkeypatch):
    from locuvi.api.auth import hash_password

    profiles.ensure_first(st, "Owner", hash_password("owner-password-1"))
    p = profiles.create(st, "Sam", hash_password("sam-password-1"))
    profiles.remove(st, p.id)
    later = datetime.now(UTC) + timedelta(days=31)

    # files can't be deleted: the entry stays, so a later run tries again
    import shutil

    real = shutil.rmtree

    def broken(*a, **k):
        raise PermissionError("busy")

    monkeypatch.setattr(shutil, "rmtree", broken)
    assert profiles.purge_removed(st, now=later) == []
    assert profiles.get(st, p.id) is not None and profiles.data_dir(st, p.id).exists()
    monkeypatch.setattr(shutil, "rmtree", real)

    # restored just before the purge runs: nothing is deleted
    profiles.restore(st, p.id)
    assert profiles.purge_removed(st, now=later) == []
    assert profiles.active(st, p.id) is not None and profiles.data_dir(st, p.id).exists()

    profiles.remove(st, p.id)
    assert profiles.purge_removed(st, now=later) == [p.id]
    assert not profiles.data_dir(st, p.id).exists()
