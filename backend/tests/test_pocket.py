"""The phone app's entry point (locuvi.pocket), run here in ordinary Python."""

from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def pocket(tmp_path, monkeypatch):
    # pocket.start sets these for the whole process; set them through monkeypatch so they are
    # put back afterwards (LOCUVI_POCKET would otherwise change every later test's database)
    for k in ("APP_ENV", "DATA_DIR", "KEY_DIR", "LOCUVI_AUTH_MODE", "COOKIE_SECURE",
              "ARCHIVE_WORKER_ENABLED", "LOCUVI_POCKET"):  # fmt: skip
        monkeypatch.setenv(k, "")
    from locuvi import pocket as p

    monkeypatch.setattr(p, "_app", None)
    loop = asyncio.new_event_loop()  # one loop for the app's life, as in the phone app
    loop.run_until_complete(p.start(str(tmp_path / "phone")))
    p.test_loop = loop
    yield p
    loop.run_until_complete(p._lifespan.__aexit__(None, None, None))
    loop.close()


def _call(p, method, url, body=None, headers=None):
    raw = json.dumps(body).encode() if body is not None else None
    h = {"content-type": "application/json", **(headers or {})}
    r = p.test_loop.run_until_complete(p.handle(method, url, json.dumps(h), raw))
    return r["status"], json.loads(r["body"] or b"null")


def test_phone_opens_straight_in_and_keeps_records(pocket, tmp_path):
    status, session = _call(pocket, "GET", "/api/v1/auth/session")
    assert status == 200 and session["authenticated"] and not session["login_required"]
    csrf = {"x-csrf-token": session["csrf_token"]}
    new = {"name": "Example Surgery", "default_rate": "300.00"}
    status, practice = _call(pocket, "POST", "/api/v1/practices", new, csrf)
    assert status == 201, practice
    status, listed = _call(pocket, "GET", "/api/v1/practices?include_archived=true")
    assert status == 200 and any(p["name"] == "Example Surgery" for p in listed)
    db = tmp_path / "phone" / "data" / "locuvi.db"
    assert db.is_file() and not (tmp_path / "phone" / "data" / "locuvi.db-wal").exists()


def test_encoded_addresses_reach_the_right_route(pocket):
    """Recently deleted ids contain ':' and are sent as %3A, as from a browser."""
    _s, session = _call(pocket, "GET", "/api/v1/auth/session")
    status, body = _call(pocket, "POST", "/api/v1/trash/document%3Anope/restore", {},
                         {"x-csrf-token": session["csrf_token"]})  # fmt: skip
    assert status == 404 and body["error"]["code"] == "document.not_found"


def test_ai_assistant_is_off_on_the_phone(pocket):
    status, cfg = _call(pocket, "GET", "/api/v1/settings/assistant")
    assert status == 200 and cfg["ready"] is False
