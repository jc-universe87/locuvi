"""Administrative agent loop with a scripted fake model. No real AI calls. Fictional data."""

from __future__ import annotations

import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from locuvi.assistant import agent, providers
from locuvi.errors import DomainError
from locuvi.models import AgentConversation, AuditEvent, Invoice
from locuvi.services import diary
from locuvi.services import invoices as svc


def resp(blocks, stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(content=blocks, stop_reason=stop, model=model)


def text(t):
    return {"type": "text", "text": t}


def use(name, args, id_=None):
    return {
        "type": "tool_use",
        "id": id_ or f"tu_{uuid.uuid4().hex[:8]}",
        "name": name,
        "input": args,
    }


class Scripted:
    """Plays back responses; records exactly what the loop sent each turn."""

    engine = "ai:fake"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.sent = []

    def run_turn(self, *, system, messages, tools):
        self.sent.append(json.loads(json.dumps(messages)))
        assert system == agent.SYSTEM_PROMPT and tools is agent.TOOLS
        t = self.turns.pop(0)
        return t(messages) if callable(t) else t


def test_tool_schemas_are_strict_and_complete():
    names = {t["name"] for t in agent.TOOLS}
    for t in agent.TOOLS:
        sch = t["input_schema"]
        assert t["strict"] is True and sch["additionalProperties"] is False
        assert set(sch["required"]) == set(sch["properties"])
        assert hasattr(agent.Tools, f"t_{t['name']}")
    # the complete tool surface: read tools + two draft-only tools; nothing sends/issues/pays
    assert names == {
        "get_overview",
        "run_checks",
        "list_practices",
        "list_sessions",
        "find_uninvoiced_sessions",
        "list_invoices",
        "get_invoice",
        "financial_summary",
        "pension_overview",
        "pension_month",
        "list_documents",
        "read_document",
        "bank_payments_to_match",
        "prepare_invoice_draft",
        "draft_email",
    }


def test_check_everything_loop(settings, session, ready):
    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 3))])

    def answer(messages):
        # the tool results came back for both calls, as JSON with real figures
        results = messages[-1]["content"]
        assert {r["type"] for r in results} == {"tool_result"}
        payload = json.loads(results[1]["content"])
        assert payload[0]["practice_name"] == ready.name and payload[0]["total"] == "600.00"
        return resp([text("September at Example Medical Practice (£600.00) isn't invoiced.")])

    fake = Scripted(
        resp(
            [
                {"type": "thinking", "thinking": "", "signature": "sig1"},
                use("run_checks", {}),
                use("find_uninvoiced_sessions", {}),
            ],
            stop="tool_use",
        ),
        answer,
    )
    out = agent.ask(session, settings, fake, "Check all outstanding admin work")
    assert "isn't invoiced" in out["answer"]
    assert [s["tool"] for s in out["steps"]] == ["run_checks", "find_uninvoiced_sessions"]
    # thinking block echoed back unchanged on the next turn
    assert fake.sent[1][1]["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "sig1",
    }
    conv = session.get(AgentConversation, out["conversation_id"])
    assert len(conv.steps_json) == 2
    ev = session.query(AuditEvent).filter(AuditEvent.event_type == "agent.asked").one()
    assert ev.metadata_json["tools"] == ["run_checks", "find_uninvoiced_sessions"]

    # follow-up continues the same conversation with full history
    fake2 = Scripted(resp([text("You're welcome.")]))
    out2 = agent.ask(session, settings, fake2, "Thanks", out["conversation_id"])
    assert out2["conversation_id"] == out["conversation_id"]
    assert fake2.sent[0][0]["content"] == "Check all outstanding admin work"
    assert fake2.sent[0][-1] == {"role": "user", "content": "Thanks"}


def test_prepare_draft_and_email_never_send(settings, session, ready, monkeypatch):
    diary.add_sessions(
        session,
        [
            diary.SessionInput(ready.id, date(2026, 9, 3)),
            diary.SessionInput(ready.id, date(2026, 8, 3)),
        ],
    )
    d = diary.invoice_month(session, ready.id, "2026-08")
    issued = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    session.expire_all()

    from locuvi import mail

    monkeypatch.setattr(mail, "_deliver", lambda *a, **k: pytest.fail("agent must not send"))
    fake = Scripted(
        resp(
            [
                use("prepare_invoice_draft", {"practice_id": ready.id, "month": "2026-09"}),
                use("draft_email", {"number": issued.invoice_number, "kind": "reminder"}),
            ],
            stop="tool_use",
        ),
        resp([text("I've prepared a draft and a reminder for you to review.")]),
    )
    out = agent.ask(session, settings, fake, "Invoice September and chase August")
    kinds = [c["type"] for c in out["created"]]
    assert kinds == ["invoice_draft", "email_draft"]
    draft = session.get(Invoice, out["created"][0]["invoice_id"])
    assert draft.status == "draft" and draft.invoice_number is None
    email = out["created"][1]
    assert email["subject"].startswith("Reminder:") and "outstanding" in email["body"]
    assert "00000000" not in json.dumps(out)  # no bank account number leaks


def test_tool_errors_are_reported_not_fatal(settings, session, ready):
    fake = Scripted(
        resp(
            [use("get_invoice", {"number": "LOC-9999-9999"}), use("nonexistent", {})],
            stop="tool_use",
        ),
        resp([text("I couldn't find that invoice.")]),
    )
    out = agent.ask(session, settings, fake, "Show LOC-9999-9999")
    assert [s["ok"] for s in out["steps"]] == [False, False]
    errs = fake.sent[1][-1]["content"]
    assert all(r["is_error"] for r in errs) and "No invoice numbered" in errs[0]["content"]
    assert out["answer"] == "I couldn't find that invoice."


def test_fallback_echo_drops_internal_blocks_before_marker():
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "a"},
        {"type": "tool_use", "id": "x", "name": "run_checks", "input": {}},
        {"type": "text", "text": "partial"},
        {"type": "fallback", "from": {"model": "m1"}, "to": {"model": "m2"}},
        {"type": "thinking", "thinking": "", "signature": "b"},
        {"type": "text", "text": "final"},
    ]
    out = agent.echo_content(blocks)
    assert [b["type"] for b in out] == ["text", "fallback", "thinking", "text"]
    assert agent.echo_content(blocks[:3]) == blocks[:3]


def test_refusal_and_step_limit(settings, session, monkeypatch):
    with pytest.raises(DomainError):
        agent.ask(session, settings, Scripted(resp([], stop="refusal")), "x")
    monkeypatch.setattr(agent, "MAX_STEPS", 2)
    loop = Scripted(*[resp([use("run_checks", {})], stop="tool_use")] * 2)
    out = agent.ask(session, settings, loop, "loop forever")
    assert "step limit" in out["answer"]


def test_provider_run_turn_request_shape():
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=[], stop_reason="end_turn", model="claude-opus-4-8")

    p = providers.AnthropicProvider(
        "sk-test", "claude-opus-5-5", client=SimpleNamespace(beta=SimpleNamespace(messages=Msgs()))
    )
    p.run_turn(system="s", messages=[{"role": "user", "content": "q"}], tools=agent.TOOLS)
    (kw,) = calls
    assert kw["fallbacks"] == "default" and kw["output_config"] == {"effort": "medium"}
    assert "tool_choice" not in kw and "thinking" not in kw and kw["tools"] is agent.TOOLS
    assert p.engine == "ai:claude-opus-4-8"


def test_api_agent(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert (
            c.post("/api/v1/assistant/ask", json={"question": "hi"}, headers=h).status_code == 400
        )
        fake = Scripted(
            resp([use("get_overview", {})], stop="tool_use"), resp([text("All quiet.")])
        )
        app.state.ai_provider_factory = lambda s: fake
        r = c.post("/api/v1/assistant/ask", json={"question": "How am I doing?"}, headers=h)
        assert r.status_code == 200 and r.json()["answer"] == "All quiet."
        cid = r.json()["conversation_id"]
        convs = c.get("/api/v1/assistant/conversations").json()
        assert convs[0]["id"] == cid and convs[0]["tools_used"] == 1
        tr = c.get(f"/api/v1/assistant/conversations/{cid}").json()
        assert [t["role"] for t in tr["turns"]] == ["user", "assistant"]
