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
from datetime import date
from typing import Any, Protocol

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

_REDACT = [
    (re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b"), "[number removed]"),  # NHS-number shaped
    (re.compile(r"\b\d{8,}\b"), "[number removed]"),
    (re.compile(r"\b(dob|d\.o\.b\.|date of birth)\s*:?\s*\S+", re.I), "[removed]"),
]


def minimise(text: str) -> str:
    """Remove long numbers (NHS numbers, account numbers) and DOBs before text leaves Locuvi."""
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

    def run_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any:
        """One step of the agent loop (tool use, adaptive thinking, explicit effort)."""
        resp = self._create(
            output_config={"effort": "medium"}, system=system, messages=messages, tools=tools
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


# ----------------------------------------------------------------------- config


def get_config(s: Session) -> AssistantConfig:
    cfg = s.get(AssistantConfig, 1)
    if cfg is None:
        cfg = AssistantConfig(id=1)
        s.add(cfg)
        s.flush()
    return cfg


def config_public(cfg: AssistantConfig, settings: Settings) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "provider": cfg.provider,
        "model": settings.ai_model,
        "key_saved": bool(cfg.api_key_ciphertext),
        "key_from_server": bool(settings.ai_api_key_override),
        "ready": cfg.enabled and bool(cfg.api_key_ciphertext or settings.ai_api_key_override),
        "weekly_brief": cfg.weekly_brief,
    }


def save_config(
    s: Session,
    secrets: SecretBox,
    *,
    enabled: bool,
    api_key: str | None,
    clear_key: bool = False,
    weekly_brief: bool | None = None,
) -> AssistantConfig:
    cfg = get_config(s)
    if weekly_brief is not None:
        cfg.weekly_brief = weekly_brief
    if api_key is not None and api_key.strip():
        key = api_key.strip()
        if len(key) < 20 or any(c.isspace() for c in key):
            raise DomainError("assistant.bad_key", "That does not look like an API key.")
        cfg.api_key_ciphertext = secrets.encrypt(key)
    elif clear_key:
        cfg.api_key_ciphertext = None
    cfg.enabled = enabled
    core.audit(
        s, "settings.assistant_saved", enabled=enabled, key_changed=bool(api_key) or clear_key
    )
    s.commit()
    return cfg


def provider_for(s: Session, settings: Settings, secrets: SecretBox) -> Provider | None:
    """The configured AI provider, or None when the assistant is off (rules engine is used)."""
    cfg = get_config(s)
    if not cfg.enabled:
        return None
    key = settings.ai_api_key_override
    if not key and cfg.api_key_ciphertext:
        try:
            key = secrets.decrypt(cfg.api_key_ciphertext)
        except SecretUnavailable:
            raise DomainError(
                "assistant.key_unreadable", "Re-enter the AI API key in Settings."
            ) from None
    if not key:
        return None
    return AnthropicProvider(key, settings.ai_model)
