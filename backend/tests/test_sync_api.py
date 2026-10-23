"""Sync through the API: setting it up, issuing with sync on, export. Fictional data only."""

from __future__ import annotations

import uuid

from test_api import Api, client_for, setup_owner_and_practice, two_october_sessions

from locuvi.sync.targets import FolderTarget


def test_issue_checks_with_other_devices_first(settings, tmp_path):
    cloud = tmp_path / "Dropbox"
    cloud.mkdir()
    with client_for(settings) as c:
        api = Api(c)
        pid = setup_owner_and_practice(api)
        assert api.get("/api/v1/sync").json()["enabled"] is False
        r = api.post("/api/v1/sync/start",
                     {"kind": "folder", "path": str(cloud), "device_name": "Laptop"})  # fmt: skip
        assert r.status_code == 200, r.text
        code = r.json()["code"]
        assert len(code) == 24 and api.get("/api/v1/sync/code").json()["code"] == code
        assert FolderTarget(cloud).read_state() is not None

        inv = api.post("/api/v1/invoices", two_october_sessions(pid)).json()
        ok = api.post(f"/api/v1/invoices/{inv['id']}/issue",
                      headers={"Idempotency-Key": uuid.uuid4().hex})  # fmt: skip
        assert ok.status_code == 200, ok.text
        assert ok.json()["invoice_number"]

        # the sync folder can't be reached: nothing is numbered, the draft waits
        (cloud / "Locuvi Sync").rename(tmp_path / "moved")
        cloud.rmdir()
        inv2 = api.post("/api/v1/invoices", two_october_sessions(pid)).json()
        r = api.post(f"/api/v1/invoices/{inv2['id']}/issue",
                     headers={"Idempotency-Key": uuid.uuid4().hex})  # fmt: skip
        assert r.status_code == 400 and r.json()["error"]["code"] == "sync.issue_offline"
        assert api.get(f"/api/v1/invoices/{inv2['id']}").json()["status"] == "draft"
        st = api.get("/api/v1/sync").json()
        assert st["enabled"] and st["last_error"]["code"] == "sync.folder_missing"

        assert api.post("/api/v1/sync/stop").json()["enabled"] is False
        r = api.post(f"/api/v1/invoices/{inv2['id']}/issue",
                     headers={"Idempotency-Key": uuid.uuid4().hex})  # fmt: skip
        assert r.status_code == 200


def test_export_file_and_import(settings, tmp_path):
    with client_for(settings) as c:
        api = Api(c)
        setup_owner_and_practice(api)
        short = api.post("/api/v1/sync/export", {"passphrase": "short"})
        assert short.status_code == 422
        r = api.post("/api/v1/sync/export", {"passphrase": "a long export passphrase"})
        assert r.status_code == 200
        assert r.headers["content-disposition"].endswith('.locuvi"')
        blob = r.content
        bad = c.post("/api/v1/sync/import", headers=api.h(), files={"file": ("x.locuvi", blob)},
                     data={"passphrase": "wrong wrong wrong"})  # fmt: skip
        assert bad.json()["error"]["code"] == "sync.wrong_passphrase"
        good = c.post("/api/v1/sync/import", headers=api.h(),
                      files={"file": ("x.locuvi", blob)},
                      data={"passphrase": "a long export passphrase"})  # fmt: skip
        assert good.status_code == 200 and good.json()["brought"] == 0  # same records already
