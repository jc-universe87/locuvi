"""Optional AI engine behind a provider-agnostic interface (docs/specs/AI_AND_AGENTS.md §4).

The model only *reads* text and returns a structured proposal; every figure it returns is
re-validated by the server and nothing is saved until the owner accepts. Only the minimum is
sent: the booking text (with long numbers redacted), practice names and today's date.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any, Protocol

import httpx
from sqlalchemy.orm import Session

from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import AssistantConfig
from locuvi.secrets_store import SecretBox, SecretUnavailable
from locuvi.services import core

log = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 30_000
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

BOOKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "unit": {"type": "string", "enum": ["am", "pm", "day", "hours"]},
                    "hours": NULLABLE_STR,
                    "practice_id": NULLABLE_STR,
                    "practice_name": NULLABLE_STR,
                    "rate": NULLABLE_STR,
                    "action": {"type": "string", "enum": ["add", "cancel"]},
                    "note": NULLABLE_STR,
                },
                "required": [
                    "date",
                    "unit",
                    "hours",
                    "practice_id",
                    "practice_name",
                    "rate",
                    "action",
                    "note",
                ],
                "additionalProperties": False,
            },
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "items", "questions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You read booking correspondence for a UK GP locum and list the sessions it books or cancels.
Your output is a proposal: the doctor reviews every item before anything is saved, and the
application re-checks all values, so prefer leaving a field null over guessing.

For each session mentioned:
- date: ISO date. Dates are UK day-first (03/04 is 3 April). When the year is missing, use the
  occurrence nearest to today's date.
- unit: "am" (morning session), "pm" (afternoon/evening session), "day" (a full day, or AM and
  PM together), or "hours" (paid by the hour; then give the number of hours in "hours" as a
  decimal string such as "4.5").
- practice_id: the id from the practice list when the booking is clearly for that practice,
  otherwise null; practice_name: the practice name as written in the text.
- rate: the agreed fee for that one session (or per hour for "hours") as a plain decimal
  string without the £ sign, e.g. "600.00", only when the text states it; otherwise null.
- action: "cancel" when the text cancels a previously booked session, otherwise "add".
- note: a short remark only when something is uncertain (e.g. "time not stated").

Ignore quoted earlier messages unless they are the only source, ignore signatures, and ignore
anything about patients — never copy patient details into the output. Put anything you could
not resolve into "questions" as short plain-English questions to the doctor. "summary" is one
sentence describing the booking. If the text is not a booking, return no items and say so in
the summary."""

# Whole lines that are about a patient (or carry identifiers) are dropped, not just masked.
_PATIENT_LINE = re.compile(
    r"\b(patients?|pt\.?|nhs\s*(no|number)|hospital\s*(no|number)|mrn|chi\s*(no|number)|"
    r"dob|d\.o\.b\.?|date of birth|born|next of kin|diagnos\w*|referral for)\b",
    re.I,
)
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email removed]"),
    (re.compile(r"\b\d{2}-\d{2}-\d{2}\s+\d{8}\b"), "[bank details removed]"),
    (re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b"), "[number removed]"),  # NHS-number shaped
    (
        re.compile(r"(?<![\d/])(?:\+44\s?(?:\(0\)\s?)?|\b0)\d(?:[\s-]?\d){8,9}\b"),
        "[phone removed]",
    ),  # fmt: skip
    (re.compile(r"\b\d{8,}\b"), "[number removed]"),  # account and other long numbers
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b"), "[postcode removed]"),
]


def minimise(text: str) -> str:
    """Best-effort removal of personal data before text leaves Locuvi.

    Drops lines about patients; masks email addresses, phone numbers, NHS-number-shaped and
    other long numbers, sort codes next to account details, and postcodes. Dates, times, fees,
    practice names and session words are kept — they are what the booking reader needs.
    """
    kept = [ln for ln in text.splitlines() if not _PATIENT_LINE.search(ln)]
    text = "\n".join(kept)
    for pattern, repl in _REDACT:
        text = pattern.sub(repl, text)
    return text[:MAX_PROMPT_CHARS]


class Provider(Protocol):
    engine: str  # recorded on every proposal, e.g. "ai:claude-opus-5-5"

    def read_booking(
        self,
        *,
        text: str,
        attachment: tuple[bytes, str] | None,
        practices: list[dict[str, str]],
        today: date,
    ) -> dict[str, Any]: ...


class AnthropicProvider:
    """Claude via the official SDK, with structured output and server-side refusal fallback."""

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        self.model = model
        self.engine = f"ai:{model}"
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=2)
        self._client = client

    def _content(
        self, text: str, attachment: tuple[bytes, str] | None, practices: list[dict[str, str]],
        today: date,
    ) -> list[dict[str, Any]]:  # fmt: skip
        context = f"Today's date: {today.isoformat()}\nPractices on file (id: name):\n" + (
            "\n".join(f"- {p['id']}: {p['name']}" for p in practices) or "- none yet"
        )
        blocks: list[dict[str, Any]] = [{"type": "text", "text": context}]
        if attachment is not None:
            data, ctype = attachment
            b64 = base64.standard_b64encode(data).decode("ascii")
            kind = "document" if ctype == "application/pdf" else "image"
            blocks.append({"type": kind, "source": {"type": "base64", "media_type": ctype,
                                                     "data": b64}})  # fmt: skip
        if text:
            blocks.append({"type": "text", "text": f"<booking>\n{minimise(text)}\n</booking>"})
        blocks.append({"type": "text", "text": "List the sessions in this booking."})
        return blocks

    def _create(self, **kw: Any) -> Any:
        """One Messages API call with refusal fallback; SDK errors become friendly ones."""
        import anthropic

        try:
            return self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **kw,
            )
        except anthropic.AuthenticationError:
            raise DomainError(
                "assistant.auth_failed", "The AI provider rejected the API key."
            ) from None
        except anthropic.RateLimitError:
            raise DomainError(
                "assistant.busy", "The AI service is busy. Try again shortly."
            ) from None
        except anthropic.APIConnectionError:
            raise DomainError("assistant.unreachable", "Could not reach the AI service.") from None
        except anthropic.APIStatusError as exc:
            log.warning("assistant request failed: status %s", exc.status_code)
            raise DomainError("assistant.failed", "The AI service could not read this.") from None

    def list_models(self) -> list[str]:
        import anthropic

        try:
            return chat_models(sorted({m.id for m in self._client.models.list(limit=100)}))
        except anthropic.AuthenticationError:
            raise DomainError(
                "assistant.auth_failed", "The AI provider rejected the API key."
            ) from None
        except anthropic.APIError:
            raise DomainError("assistant.unreachable", "Could not reach the AI service.") from None

    def run_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any:
        """One step of the agent loop (tool use, adaptive thinking, explicit effort)."""
        resp = self._create(
            output_config={"effort": "medium"},
            system=system,
            messages=for_anthropic(messages),
            tools=tools,
        )
        served = getattr(resp, "model", None)
        if served and served != self.model:
            self.engine = f"ai:{served}"
        return resp

    def read_booking(
        self,
        *,
        text: str,
        attachment: tuple[bytes, str] | None,
        practices: list[dict[str, str]],
        today: date,
    ) -> dict[str, Any]:
        resp = self._create(
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": BOOKING_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": self._content(text, attachment, practices, today)}
            ],
        )
        if resp.stop_reason == "refusal":
            raise DomainError("assistant.refused", "The AI declined to read this document.")
        if resp.stop_reason == "max_tokens":
            raise DomainError("assistant.failed", "The AI service could not read this.")
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(raw)
        except ValueError:
            raise DomainError("assistant.failed", "The AI service could not read this.") from None
        if not isinstance(data, dict):
            raise DomainError("assistant.failed", "The AI service could not read this.")
        served = getattr(resp, "model", None)
        if served and served != self.model:
            self.engine = f"ai:{served}"  # a fallback model answered; record which
        return data


# ------------------------------------------------------------ other providers


CUSTOM = "custom"


@dataclass(frozen=True)
class ProviderInfo:
    label: str
    default_model: str
    base_url: str | None  # OpenAI-compatible endpoint; None for Anthropic (own SDK)
    key_url: str  # where the owner creates a key
    models_url: str  # the company's own model list
    pricing_url: str  # the company's own price list
    country: str  # ISO code, shown as a flag
    vision: bool = True  # can read photos of bookings (see reads_photos for per-model rules)
    # How the booking reply is forced into JSON: "strict" (json_schema, strict), "schema"
    # (json_schema), "object" (json_object) or "none" (prompt only; the server still checks it)
    json_mode: str = "object"
    tokens_field: str = "max_tokens"
    agent: bool = True  # supports tool calling, so Ask Locuvi and the weekly brief work
    can_list: bool = True  # GET /models works; otherwise Check key sends a one-word request


# Defaults are only a starting point: model names change often, so the owner can pick another
# from the provider's own list (Settings › AI assistant › Check key).
PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "OpenAI (GPT)", "gpt-5.5", "https://api.openai.com/v1",
        "https://platform.openai.com/api-keys",
        "https://platform.openai.com/docs/models", "https://openai.com/api/pricing/", "US",
        json_mode="strict", tokens_field="max_completion_tokens",
    ),
    "anthropic": ProviderInfo(
        "Anthropic (Claude)", "claude-opus-5-5", None,
        "https://console.anthropic.com/settings/keys",
        "https://docs.claude.com/en/docs/about-claude/models/overview",
        "https://claude.com/pricing#api", "US",
    ),
    "gemini": ProviderInfo(
        "Google (Gemini)", "gemini-flash-latest",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "https://aistudio.google.com/apikey",
        "https://ai.google.dev/gemini-api/docs/models",
        "https://ai.google.dev/gemini-api/docs/pricing", "US",
    ),
    "xai": ProviderInfo(
        "xAI (Grok)", "grok-4", "https://api.x.ai/v1", "https://console.x.ai",
        "https://docs.x.ai/docs/models", "https://x.ai/api", "US",
    ),
    "mistral": ProviderInfo(
        "Mistral", "mistral-large-latest", "https://api.mistral.ai/v1",
        "https://console.mistral.ai/api-keys",
        "https://docs.mistral.ai/getting-started/models/",
        "https://mistral.ai/pricing#api-pricing", "FR",
    ),
    "cohere": ProviderInfo(
        "Cohere (Command)", "command-a-plus-05-2026", "https://api.cohere.ai/compatibility/v1",
        "https://dashboard.cohere.com/api-keys",
        "https://docs.cohere.com/docs/models", "https://cohere.com/pricing", "CA",
        vision=False, json_mode="schema", can_list=False,
    ),
    "deepseek": ProviderInfo(
        "DeepSeek", "deepseek-v4-flash", "https://api.deepseek.com",
        "https://platform.deepseek.com/api_keys",
        "https://api-docs.deepseek.com/quick_start/pricing",
        "https://api-docs.deepseek.com/quick_start/pricing", "CN",
        vision=False,
    ),
    "alibaba": ProviderInfo(
        "Alibaba (Qwen)", "qwen3.6-plus",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "https://modelstudio.console.alibabacloud.com/",
        "https://www.alibabacloud.com/help/en/model-studio/models",
        "https://www.alibabacloud.com/help/en/model-studio/models", "CN",
        vision=False,
    ),
    "moonshot": ProviderInfo(
        "Moonshot AI (Kimi)", "kimi-k2.6", "https://api.moonshot.ai/v1",
        "https://platform.moonshot.ai/console/api-keys",
        "https://platform.moonshot.ai/docs", "https://platform.moonshot.ai/docs/pricing/chat",
        "CN", vision=False,
    ),
    "zai": ProviderInfo(
        "Z.ai (GLM)", "glm-5.1", "https://api.z.ai/api/paas/v4",
        "https://z.ai/manage-apikey/apikey-list",
        "https://docs.z.ai/guides/overview/pricing", "https://docs.z.ai/guides/overview/pricing",
        "CN", vision=False, can_list=False,
    ),
    "minimax": ProviderInfo(
        "MiniMax", "MiniMax-M2.7", "https://api.minimax.io/v1",
        "https://platform.minimax.io/user-center/basic-information/interface-key",
        "https://platform.minimax.io/docs", "https://platform.minimax.io/docs", "CN",
        vision=False, json_mode="none", can_list=False,
    ),
    "openrouter": ProviderInfo(
        "OpenRouter (many companies, one key)", "openrouter/auto",
        "https://openrouter.ai/api/v1", "https://openrouter.ai/keys",
        "https://openrouter.ai/models", "https://openrouter.ai/models", "US",
    ),
    # A model the owner runs themselves (Ollama, LM Studio, vLLM, llama.cpp, LocalAI…) or a
    # company server with an OpenAI-style API. The address and model come from Settings; a key
    # is optional. Replies are parsed from the prompt alone, since local servers vary.
    CUSTOM: ProviderInfo(
        "Your own server (Ollama, LM Studio…)", "", None, "", "", "", "",
        vision=False, json_mode="none",
    ),
}  # fmt: skip

# Some models write their reasoning into the answer between these tags; it is never shown or
# parsed as the answer.
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_VISION_NAME = re.compile(r"vision|llava|-vl\b|vl-|\d(\.\d+)?v\b", re.I)
# Cloud metadata services: never reachable through an owner-entered AI address
_METADATA = {"metadata.google.internal", "metadata", "169.254.169.254", "fd00:ec2::254"}


def validate_ai_url(raw: str) -> str:
    """The owner's own AI server address: http(s), no credentials or query; private and local
    addresses are allowed (that's the point), cloud metadata and link-local ones are not."""
    import ipaddress
    from urllib.parse import urlsplit

    url = (raw or "").strip().rstrip("/")
    bad = DomainError(
        "assistant.bad_url", "Enter the server address, for example http://192.168.1.20:11434/v1."
    )
    if not url or len(url) > 300 or any(c.isspace() for c in url):
        raise bad
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise bad
    if parts.username or parts.password or parts.query or parts.fragment:
        raise bad
    host = parts.hostname.lower().rstrip(".")
    if host in _METADATA:
        raise bad
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None and (ip.is_link_local or ip.is_multicast or ip.is_unspecified):
        raise bad
    try:
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        raise bad from None
    return url


_JSON_ONLY = (
    "\n\nReply with one JSON object only (no other text) that follows this JSON schema:\n"
    + json.dumps(BOOKING_SCHEMA)
)
_FAILED = ("assistant.failed", "The AI service could not read this.")


def _http_error(exc: Exception) -> DomainError:
    """Provider HTTP problems as the same friendly errors the Anthropic path uses."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return DomainError("assistant.auth_failed", "The AI provider rejected the API key.")
        if code == 429:
            return DomainError("assistant.busy", "The AI service is busy. Try again shortly.")
        log.warning("assistant request failed: status %s", code)
        return DomainError(*_FAILED)
    return DomainError("assistant.unreachable", "Could not reach the AI service.")


def pdf_text(data: bytes) -> str:
    """Text layer of a PDF (for providers that cannot take PDF files directly)."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:20]).strip()
    except Exception:  # noqa: BLE001 - unreadable PDF: treated as "no text"
        return ""


def _tool_schema(schema: dict[str, Any], provider: str) -> dict[str, Any]:
    if provider != "gemini":
        return schema
    # Gemini's OpenAI layer accepts a smaller JSON-schema subset
    drop = {"additionalProperties", "pattern"}
    if isinstance(schema, dict):
        return {k: _tool_schema(v, provider) for k, v in schema.items() if k not in drop}
    if isinstance(schema, list):
        return [_tool_schema(v, provider) for v in schema]
    return schema


def to_chat_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stored (Anthropic-style) conversation as OpenAI chat messages.

    Thinking and fallback blocks are Claude-internal and are left out.
    """
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        blocks = [b for b in content or [] if isinstance(b, dict)]
        if m["role"] == "assistant":
            text = "\n\n".join(b["text"] for b in blocks if b.get("type") == "text")
            calls = []
            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                call = {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                }
                if b.get("extra_content"):  # e.g. Gemini's thought signature, returned unchanged
                    call["extra_content"] = b["extra_content"]
                calls.append(call)
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            reasoning = "".join(b.get("text", "") for b in blocks if b.get("type") == "reasoning")
            if reasoning:  # DeepSeek thinking mode needs it back after a tool call
                msg["reasoning_content"] = reasoning
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        for b in blocks:
            if b.get("type") == "tool_result":
                body = b.get("content")
                if not isinstance(body, str):
                    body = json.dumps(body)
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": body})
        text = "\n\n".join(b["text"] for b in blocks if b.get("type") == "text")
        if text:
            out.append({"role": "user", "content": text})
    return out


def for_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The conversation without other companies' reasoning metadata (Claude rejects it)."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = [
                {k: v for k, v in b.items() if k != "extra_content"} if isinstance(b, dict) else b
                for b in content
                if not (isinstance(b, dict) and b.get("type") == "reasoning")
            ]
            if not content:
                continue
        out.append({**m, "content": content})
    return out


# Model IDs that can't hold a conversation (embeddings, speech, images, video, moderation)
_NOT_CHAT = re.compile(
    r"embed|tts|audio|transcri|whisper|speech|dall-e|imagen|image|veo|video|moderation|"
    r"realtime|live|aqa|rerank|ocr",
    re.I,
)


def chat_models(ids: list[str]) -> list[str]:
    return [i for i in ids if not _NOT_CHAT.search(i)]


def reads_photos(provider: str, model: str) -> bool:
    """Whether photos can be sent: the company's main models, or a vision model chosen by name
    (for example deepseek-v4-flash-vision-exp, qwen-vl-max or glm-4.5v)."""
    return PROVIDERS[provider].vision or bool(_VISION_NAME.search(model))


class CompatibleProvider:
    """Every company except Anthropic, through its OpenAI-style chat completions API.

    Same contract as AnthropicProvider: read_booking returns a dict that the server
    re-validates; run_turn returns Anthropic-shaped blocks so the agent loop is shared.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        client: Any = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self.info = PROVIDERS[provider]
        self.base_url = (base_url or self.info.base_url or "").rstrip("/")
        self.model = model
        self.engine = f"ai:{provider}/{model}"
        self._key = api_key
        # a model on the owner's own computer can be slow
        self._client = client or httpx.Client(timeout=300.0 if provider == CUSTOM else 120.0)
        self.supports_agent = self.info.agent

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def _post(self, body: dict[str, Any], max_tokens: int = 16000) -> dict[str, Any]:
        headers = self._headers()
        if self.provider == "openrouter":
            headers["X-Title"] = "Locuvi"
        try:
            r = self._client.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model, self.info.tokens_field: max_tokens, **body},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise _http_error(exc) from None
        except ValueError:
            raise DomainError(*_FAILED) from None
        if not isinstance(data, dict) or not data.get("choices"):
            raise DomainError(*_FAILED)
        served = data.get("model")
        if isinstance(served, str) and served and served != self.model:
            self.engine = f"ai:{self.provider}/{served}"
        return data

    def _user_content(
        self, text: str, attachment: tuple[bytes, str] | None, practices: list[dict[str, str]],
        today: date,
    ) -> list[dict[str, Any]]:  # fmt: skip
        context = f"Today's date: {today.isoformat()}\nPractices on file (id: name):\n" + (
            "\n".join(f"- {p['id']}: {p['name']}" for p in practices) or "- none yet"
        )
        parts: list[dict[str, Any]] = [{"type": "text", "text": context}]
        if attachment is not None:
            data, ctype = attachment
            if ctype == "application/pdf":
                extracted = pdf_text(data)
                if not extracted and not text:
                    raise DomainError(
                        "assistant.scan_unsupported",
                        "This AI provider can't read scanned PDFs. Paste the text instead.",
                    )
                if extracted:
                    text = f"{extracted}\n\n{text}".strip()
            elif reads_photos(self.provider, self.model):
                b64 = base64.standard_b64encode(data).decode("ascii")
                parts.append({"type": "image_url",
                              "image_url": {"url": f"data:{ctype};base64,{b64}"}})  # fmt: skip
            elif not text:
                raise DomainError(
                    "assistant.scan_unsupported",
                    "This AI provider can't read photos. Paste the text instead.",
                )
        if text:
            parts.append({"type": "text", "text": f"<booking>\n{minimise(text)}\n</booking>"})
        parts.append({"type": "text", "text": "List the sessions in this booking."})
        return parts

    def read_booking(
        self,
        *,
        text: str,
        attachment: tuple[bytes, str] | None,
        practices: list[dict[str, str]],
        today: date,
    ) -> dict[str, Any]:
        mode = self.info.json_mode
        system = SYSTEM_PROMPT if mode == "strict" else SYSTEM_PROMPT + _JSON_ONLY
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",
                 "content": self._user_content(text, attachment, practices, today)},
            ],
        }  # fmt: skip
        if mode in ("strict", "schema"):
            schema: dict[str, Any] = {"name": "booking", "schema": BOOKING_SCHEMA}
            if mode == "strict":
                schema["strict"] = True
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
        elif mode == "object":
            body["response_format"] = {"type": "json_object"}
        data = self._post(body)
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        if choice.get("finish_reason") == "content_filter" or msg.get("refusal"):
            raise DomainError("assistant.refused", "The AI declined to read this document.")
        raw = _THINK.sub("", msg.get("content") or "").strip()
        if raw.startswith("```"):  # some models wrap JSON in a code fence
            raw = raw.strip("`").removeprefix("json").strip()
        if not raw.startswith("{") and "{" in raw:  # a sentence before the JSON object
            raw = raw[raw.index("{") : raw.rindex("}") + 1]
        try:
            out = json.loads(raw)
        except ValueError:
            raise DomainError(*_FAILED) from None
        if not isinstance(out, dict):
            raise DomainError(*_FAILED)
        return out

    def run_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any:
        """One agent step; the reply comes back as Anthropic-style blocks."""
        data = self._post(
            {
                "messages": to_chat_messages(system, messages),
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": _tool_schema(t["input_schema"], self.provider),
                        },
                    }
                    for t in tools
                ],
            }
        )
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        blocks: list[dict[str, Any]] = []
        if msg.get("reasoning_content"):
            blocks.append({"type": "reasoning", "text": str(msg["reasoning_content"])})
        answer = _THINK.sub("", str(msg.get("content") or "")).strip()
        if answer:
            blocks.append({"type": "text", "text": answer})
        for i, call in enumerate(msg.get("tool_calls") or []):
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            block = {
                "type": "tool_use",
                "id": re.sub(r"[^A-Za-z0-9_-]", "_", call.get("id") or f"call_{i}"),
                "name": fn.get("name", ""),
                "input": args if isinstance(args, dict) else {},
            }
            if call.get("extra_content"):
                block["extra_content"] = call["extra_content"]
            blocks.append(block)
        finish = choice.get("finish_reason")
        if any(b["type"] == "tool_use" for b in blocks):
            stop = "tool_use"
        elif finish == "content_filter" or msg.get("refusal"):
            stop = "refusal"
        elif finish == "length":
            stop = "max_tokens"
        else:
            stop = "end_turn"
        return SimpleNamespace(stop_reason=stop, content=blocks, model=data.get("model"))

    def _ping(self) -> None:
        """A one-word request, for companies without a model list: proves the key works."""
        self._post({"messages": [{"role": "user", "content": "Reply with OK."}]}, max_tokens=5)

    def list_models(self) -> list[str]:
        """The models this key can use, or [] when the company has no list (key still checked)."""
        if not self.info.can_list:
            self._ping()
            return []
        try:
            r = self._client.get(f"{self.base_url}/models", headers=self._headers())
            r.raise_for_status()
            items = r.json().get("data") or []
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404, 405):  # no list here after all
                self._ping()
                return []
            raise _http_error(exc) from None
        except httpx.HTTPError as exc:
            raise _http_error(exc) from None
        except (ValueError, AttributeError):
            raise DomainError(*_FAILED) from None
        ids = {str(m.get("id", "")).removeprefix("models/") for m in items if isinstance(m, dict)}
        return chat_models(sorted(i for i in ids if i))[:300]


# ----------------------------------------------------------------------- config


def get_config(s: Session) -> AssistantConfig:
    cfg = s.get(AssistantConfig, 1)
    if cfg is None:
        cfg = AssistantConfig(id=1)
        s.add(cfg)
        s.flush()
    return cfg


def model_for(cfg: AssistantConfig, settings: Settings) -> str:
    provider = cfg.provider if cfg.provider in PROVIDERS else "anthropic"
    if cfg.model:
        return cfg.model
    if provider == "anthropic":
        return settings.ai_model
    return PROVIDERS[provider].default_model


def _server_key(cfg: AssistantConfig, settings: Settings) -> str | None:
    # ANTHROPIC_API_KEY_FILE on the server only ever goes to Anthropic
    return settings.ai_api_key_override if cfg.provider == "anthropic" else None


def config_public(cfg: AssistantConfig, settings: Settings) -> dict[str, Any]:
    server = bool(_server_key(cfg, settings))
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "model": model_for(cfg, settings),
        "model_custom": bool(cfg.model),
        "reads_photos": reads_photos(cfg.provider, model_for(cfg, settings))
        if cfg.provider in PROVIDERS
        else True,
        "key_saved": bool(cfg.api_key_ciphertext),
        "key_from_server": server,
        "base_url": cfg.base_url or "",
        "ready": cfg.enabled
        and not on_phone()
        and (
            bool(cfg.base_url and cfg.model)
            if cfg.provider == CUSTOM
            else bool(cfg.api_key_ciphertext or server)
        ),
        "weekly_brief": cfg.weekly_brief,
        "providers": [
            {"id": pid, "label": info.label, "default_model": info.default_model,
             "key_url": info.key_url, "models_url": info.models_url,
             "pricing_url": info.pricing_url, "country": info.country,
             "reads_photos": info.vision, "ask": info.agent}
            for pid, info in PROVIDERS.items()
        ],
    }  # fmt: skip


def save_config(
    s: Session,
    secrets: SecretBox,
    *,
    enabled: bool,
    api_key: str | None,
    clear_key: bool = False,
    weekly_brief: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AssistantConfig:
    cfg = get_config(s)
    if weekly_brief is not None:
        cfg.weekly_brief = weekly_brief
    if provider is not None and provider != cfg.provider:
        if provider not in PROVIDERS:
            raise DomainError("assistant.bad_provider", "Choose an AI provider from the list.")
        # a key belongs to one provider: never send one company's key to another
        cfg.provider = provider
        cfg.api_key_ciphertext = None
        cfg.model = None
        cfg.base_url = None
    if model is not None:
        m = model.strip()
        if m and (len(m) > 120 or any(c.isspace() for c in m)):
            raise DomainError("assistant.bad_model", "That does not look like a model name.")
        cfg.model = m or None
    if base_url is not None and cfg.provider == CUSTOM:
        cfg.base_url = validate_ai_url(base_url) if base_url.strip() else None
    if api_key is not None and api_key.strip():
        key = api_key.strip()
        too_short = len(key) < (1 if cfg.provider == CUSTOM else 20)  # own servers: any token
        if too_short or any(c.isspace() for c in key):
            raise DomainError("assistant.bad_key", "That does not look like an API key.")
        cfg.api_key_ciphertext = secrets.encrypt(key)
    elif clear_key:
        cfg.api_key_ciphertext = None
    cfg.enabled = enabled
    core.audit(
        s,
        "settings.assistant_saved",
        enabled=enabled,
        provider=cfg.provider,
        key_changed=bool(api_key) or clear_key,
    )
    s.commit()
    return cfg


def _key(cfg: AssistantConfig, settings: Settings, secrets: SecretBox) -> str | None:
    key = _server_key(cfg, settings)
    if not key and cfg.api_key_ciphertext:
        try:
            key = secrets.decrypt(cfg.api_key_ciphertext)
        except SecretUnavailable:
            raise DomainError(
                "assistant.key_unreadable", "Re-enter the AI API key in Settings."
            ) from None
    return key


def build(provider: str, key: str, model: str, base_url: str | None = None) -> Any:
    if provider == "anthropic":
        return AnthropicProvider(key, model)
    return CompatibleProvider(provider, key, model, base_url=base_url)


def on_phone() -> bool:
    """The phone app (locuvi/pocket.py) can't reach AI companies yet: the assistant stays off
    there, even when a computer synced its settings across (the rules engine still reads
    bookings)."""
    import os

    return os.environ.get("LOCUVI_POCKET") == "1"


def provider_for(s: Session, settings: Settings, secrets: SecretBox) -> Provider | None:
    """The configured AI provider, or None when the assistant is off (rules engine is used)."""
    cfg = get_config(s)
    if not cfg.enabled or cfg.provider not in PROVIDERS or on_phone():
        return None
    key = _key(cfg, settings, secrets)
    if cfg.provider == CUSTOM:  # own server: the address and model matter, a key is optional
        if not cfg.base_url or not cfg.model:
            return None
        return build(CUSTOM, key or "", cfg.model, cfg.base_url)
    if not key:
        return None
    return build(cfg.provider, key, model_for(cfg, settings))


def check_key(
    s: Session, settings: Settings, secrets: SecretBox, factory: Any = None
) -> dict[str, Any]:
    """Ask the provider which models this key can use: a free check that the key works."""
    cfg = get_config(s)
    key = _key(cfg, settings, secrets)
    if cfg.provider == CUSTOM:
        if not cfg.base_url:
            raise DomainError("assistant.no_url", "Add your server's address first.")
        p = (factory or build)(CUSTOM, key or "", cfg.model or "", cfg.base_url)
        return {"ok": True, "models": p.list_models()}
    if not key or cfg.provider not in PROVIDERS:
        raise DomainError("assistant.no_key", "Add your API key first.")
    p = (factory or build)(cfg.provider, key, model_for(cfg, settings))
    models = p.list_models()
    return {"ok": True, "models": models}
