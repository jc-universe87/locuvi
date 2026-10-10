"""Choice of AI provider with the owner's own key. Fake HTTP only: never a real AI API."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from locuvi.assistant import agent, providers
from locuvi.errors import DomainError
from locuvi.secrets_store import SecretBox

TODAY = date(2026, 10, 8)
KEY = "sk-fake-" + "x" * 32


def fake_http(reply, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        body = reply(req) if callable(reply) else reply
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def chat(message, finish="stop", model=None):
    return {"model": model, "choices": [{"message": message, "finish_reason": finish}]}


@pytest.mark.parametrize("pid", ["openai", "gemini", "deepseek", "mistral", "xai", "openrouter"])
def test_booking_read_through_each_provider(pid):
    calls: list[httpx.Request] = []
    booking = {"summary": "One session", "items": [], "questions": []}
    content = json.dumps(booking)
    if pid == "gemini":
        content = f"```json\n{content}\n```"  # tolerated
    client = fake_http(chat({"role": "assistant", "content": content}), calls)
    info = providers.PROVIDERS[pid]
    p = providers.CompatibleProvider(pid, KEY, info.default_model, client=client)
    out = p.read_booking(
        text="Cover 12 Oct AM.\nPatient DOB 01/02/1960\nReply to rota@example.invalid",
        attachment=None,
        practices=[{"id": "p1", "name": "Example Medical Practice"}],
        today=TODAY,
    )
    assert out == booking
    (req,) = calls
    assert str(req.url) == f"{info.base_url}/chat/completions"
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    sent = json.loads(req.content)
    assert sent["model"] == info.default_model
    fmt = sent["response_format"]["type"]
    assert fmt == ("json_schema" if pid == "openai" else "json_object")
    text = json.dumps(sent["messages"])
    assert "12 Oct AM" in text and "01/02/1960" not in text and "example.invalid" not in text
    assert KEY not in text
    assert p.engine == f"ai:{pid}/{info.default_model}"


def test_errors_are_friendly_and_photos_respect_provider_ability():
    for status, code in [(401, "assistant.auth_failed"), (429, "assistant.busy"),
                         (500, "assistant.failed")]:  # fmt: skip
        client = fake_http(httpx.Response(status, json={"error": "x"}), [])
        p = providers.CompatibleProvider("openai", KEY, "m", client=client)
        with pytest.raises(DomainError) as e:
            p.read_booking(text="x", attachment=None, practices=[], today=TODAY)
        assert e.value.code == code

    refuse = chat({"role": "assistant", "content": None, "refusal": "no"})
    p = providers.CompatibleProvider("openai", KEY, "m", client=fake_http(refuse, []))
    with pytest.raises(DomainError) as e:
        p.read_booking(text="x", attachment=None, practices=[], today=TODAY)
    assert e.value.code == "assistant.refused"

    # DeepSeek can't see images: a photo alone is refused before anything is sent
    calls: list[httpx.Request] = []
    p = providers.CompatibleProvider("deepseek", KEY, "m", client=fake_http({}, calls))
    with pytest.raises(DomainError) as e:
        p.read_booking(text="", attachment=(b"\x89PNG", "image/png"), practices=[], today=TODAY)
    assert e.value.code == "assistant.scan_unsupported" and calls == []

    # providers that can see get the photo as an image part
    ok = chat({"role": "assistant", "content": '{"summary":"","items":[],"questions":[]}'})
    p = providers.CompatibleProvider("openai", KEY, "m", client=fake_http(ok, calls))
    p.read_booking(text="", attachment=(b"\x89PNG", "image/png"), practices=[], today=TODAY)
    assert "data:image/png;base64," in calls[-1].content.decode()


def test_agent_loop_runs_on_an_openai_style_provider(session, settings, ready):
    calls: list[httpx.Request] = []
    replies = iter(
        [
            chat({"role": "assistant", "content": None,
                  "tool_calls": [{"id": "call_1", "type": "function",
                                  "function": {"name": "list_practices", "arguments": "{}"}}]},
                 finish="tool_calls"),
            chat({"role": "assistant", "content": "You have one practice."}),
        ]
    )  # fmt: skip
    p = providers.CompatibleProvider(
        "gemini", KEY, "gemini-flash-latest", client=fake_http(lambda r: next(replies), calls)
    )
    out = agent.ask(session, settings, p, "Which practices do I have?")
    assert out["answer"] == "You have one practice."
    assert [s["tool"] for s in out["steps"]] == ["list_practices"]
    second = json.loads(calls[1].content)
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["id"] == "call_1"
    assert second["messages"][3]["tool_call_id"] == "call_1"
    assert "Example Medical Practice" in second["messages"][3]["content"]
    tools = second["tools"]
    assert tools[0]["type"] == "function" and "additionalProperties" not in json.dumps(tools)


def test_conversation_history_converts_without_claude_internal_blocks():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "secret", "signature": "s"},
            {"type": "text", "text": "Looking"},
            {"type": "tool_use", "id": "t1", "name": "get_overview", "input": {}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": "{}"}]},
    ]  # fmt: skip
    out = providers.to_chat_messages("sys", msgs)
    assert "secret" not in json.dumps(out)
    assert out[2]["content"] == "Looking" and out[3] == {
        "role": "tool", "tool_call_id": "t1", "content": "{}"
    }  # fmt: skip


def test_switching_provider_forgets_the_old_key(session, settings):
    box = SecretBox(settings)
    providers.save_config(session, box, enabled=True, api_key="sk-ant-" + "y" * 40)
    assert isinstance(providers.provider_for(session, settings, box), providers.AnthropicProvider)

    # another company never receives the Anthropic key
    providers.save_config(session, box, enabled=True, api_key=None, provider="deepseek")
    assert providers.provider_for(session, settings, box) is None
    pub = providers.config_public(providers.get_config(session), settings)
    assert pub["provider"] == "deepseek" and not pub["key_saved"] and not pub["ready"]
    assert pub["model"] == "deepseek-v4-flash"
    assert {p["id"] for p in pub["providers"]} >= {"anthropic", "openai", "gemini", "deepseek"}

    providers.save_config(session, box, enabled=True, api_key=KEY, model="deepseek-v4-pro")
    p = providers.provider_for(session, settings, box)
    assert isinstance(p, providers.CompatibleProvider) and p.model == "deepseek-v4-pro"
    assert KEY not in json.dumps(providers.config_public(providers.get_config(session), settings))

    with pytest.raises(DomainError):
        providers.save_config(session, box, enabled=True, api_key=None, provider="nope")
    with pytest.raises(DomainError):
        providers.save_config(session, box, enabled=True, api_key=None, model="bad model")


def test_server_key_file_is_only_used_for_anthropic(session, settings):
    from dataclasses import replace

    st = replace(settings, ai_api_key_override="sk-ant-" + "z" * 40)
    box = SecretBox(st)
    providers.save_config(session, box, enabled=True, api_key=None)
    assert isinstance(providers.provider_for(session, st, box), providers.AnthropicProvider)
    providers.save_config(session, box, enabled=True, api_key=None, provider="openai")
    assert providers.provider_for(session, st, box) is None
    assert providers.config_public(providers.get_config(session), st)["key_from_server"] is False


def test_check_key_lists_models_via_the_api(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    calls: list[httpx.Request] = []
    listing = {"data": [{"id": "models/gemini-flash-latest"}, {"id": "models/gemini-pro-latest"}]}

    def lister(pid, key, model):
        return providers.CompatibleProvider(pid, key, model, client=fake_http(listing, calls))

    app = create_app(settings)
    with TestClient(app) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        app.state.ai_model_lister = lister
        r = c.post("/api/v1/settings/assistant/check", headers=h)
        assert r.status_code == 400 and r.json()["error"]["code"] == "assistant.no_key"
        r = c.put("/api/v1/settings/assistant", headers=h,
                  json={"enabled": True, "provider": "gemini", "api_key": KEY})  # fmt: skip
        assert r.status_code == 200 and r.json()["ready"] and "api_key" not in r.json()
        r = c.post("/api/v1/settings/assistant/check", headers=h)
        assert r.json() == {"ok": True, "models": ["gemini-flash-latest", "gemini-pro-latest"]}
        assert str(calls[0].url).endswith("/v1beta/openai/models")
