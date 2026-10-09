"""Bevro / MCP endpoint: token auth, scopes, protocol flow, audit. Fictional data only."""

from __future__ import annotations

import json
from datetime import date

import pytest

from locuvi import db
from locuvi.models import AgentToken, AuditEvent, Invoice
from locuvi.services import diary


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        c.headers["X-CSRF-Token"] = c.get("/api/v1/auth/session").json()["csrf_token"]
        yield c


def rpc(c, token, method, params=None, id_=1, **headers):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if id_ is not None:
        body["id"] = id_
    h = {"Authorization": f"Bearer {token}", **headers} if token else headers
    return c.post(
        "/mcp", content=json.dumps(body), headers={"Content-Type": "application/json", **h}
    )


def make_token(c, allow_drafts=False):
    r = c.post("/api/v1/settings/agents", json={"name": "Bevro", "allow_drafts": allow_drafts})
    assert r.status_code == 201
    return r.json()


def test_token_lifecycle_and_storage(client):
    created = make_token(client)
    tok = created["token"]
    assert tok.startswith("lcv_") and created["hint"] == tok[-4:]
    listed = client.get("/api/v1/settings/agents").json()
    assert listed["endpoint_path"] == "/mcp" and "token" not in listed["tokens"][0]
    s = db.new_session()
    row = s.query(AgentToken).one()
    assert row.token_hash != tok and tok not in row.token_hash
    s.close()
    assert rpc(client, tok, "ping").json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert client.delete(f"/api/v1/settings/agents/{created['id']}").status_code == 204
    assert rpc(client, tok, "ping").status_code == 401


def test_auth_and_origin_guard(client):
    tok = make_token(client)["token"]
    assert rpc(client, None, "ping").status_code == 401
    assert rpc(client, "lcv_wrong", "ping").status_code == 401
    assert rpc(client, tok, "ping", Origin="https://evil.example.invalid").status_code == 403
    # session cookie alone is not enough for /mcp
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    assert client.get("/mcp").status_code == 405


def test_protocol_flow_read_only(client, settings):
    tok = make_token(client)["token"]
    init = rpc(
        client,
        tok,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "bevro", "version": "1"},
        },
    ).json()
    res = init["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["serverInfo"]["name"] == "locuvi"
    assert "tools" in res["capabilities"]
    assert rpc(client, tok, "notifications/initialized", id_=None).status_code == 202
    tools = {t["name"]: t for t in rpc(client, tok, "tools/list").json()["result"]["tools"]}
    assert "prepare_invoice_draft" not in tools and "draft_email" not in tools
    assert tools["get_overview"]["annotations"]["readOnlyHint"] is True
    assert tools["list_sessions"]["inputSchema"]["additionalProperties"] is False

    r = rpc(client, tok, "tools/call", {"name": "get_overview", "arguments": {}}).json()
    assert r["result"]["isError"] is False
    assert "outstanding_total" in json.loads(r["result"]["content"][0]["text"])
    # draft tools are not callable with a read-only token
    r = rpc(
        client,
        tok,
        "tools/call",
        {"name": "prepare_invoice_draft", "arguments": {"practice_id": "x", "month": "2026-09"}},
    )
    assert r.json()["error"]["code"] == -32602
    # bad arguments rejected before running
    r = rpc(client, tok, "tools/call", {"name": "get_invoice", "arguments": {"nope": 1}})
    assert r.json()["error"]["code"] == -32602
    # tool-level failure is a result with isError, not a protocol error
    r = rpc(client, tok, "tools/call", {"name": "get_invoice", "arguments": {"number": "LOC-0"}})
    assert r.json()["result"]["isError"] is True
    assert rpc(client, tok, "resources/list").json()["error"]["code"] == -32601

    s = db.new_session()
    calls = s.query(AuditEvent).filter(AuditEvent.event_type == "bevro.tool_call").all()
    assert [c.metadata_json["tool"] for c in calls] == ["get_overview", "get_invoice"]
    assert s.query(AgentToken).one().last_used_at is not None
    s.close()


def test_drafts_token_can_prepare_but_not_issue(client, settings):
    from conftest import fill_profile, make_practice

    s = db.new_session()
    fill_profile(s)
    p = make_practice(s)
    diary.add_sessions(s, [diary.SessionInput(p.id, date(2026, 9, 3))])
    pid = p.id
    s.close()
    tok = make_token(client, allow_drafts=True)["token"]
    names = {t["name"] for t in rpc(client, tok, "tools/list").json()["result"]["tools"]}
    assert {"prepare_invoice_draft", "draft_email"} <= names
    assert not {n for n in names if n.startswith(("issue", "send", "record", "submit"))}
    r = rpc(
        client,
        tok,
        "tools/call",
        {"name": "prepare_invoice_draft", "arguments": {"practice_id": pid, "month": "2026-09"}},
    )
    out = json.loads(r.json()["result"]["content"][0]["text"])
    s = db.new_session()
    inv = s.get(Invoice, out["draft_invoice_id"])
    assert inv.status == "draft" and inv.invoice_number is None
    s.close()


def test_batch_requests(client):
    tok = make_token(client)["token"]
    body = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    r = client.post(
        "/mcp",
        content=json.dumps(body),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
    )
    assert [x["id"] for x in r.json()] == [1, 2]
    bad = client.post("/mcp", content=b"{not json", headers={"Authorization": f"Bearer {tok}"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
