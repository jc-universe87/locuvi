"""Administrative agent: answers questions and prepares work using Locuvi's own records.

Spec §3 (agentic workflow), §B/C/D/E/F/G. The model gets *tools*, not the database:
- read tools wrap the service layer and return only the fields needed (no bank details,
  secrets or passwords exist in any tool output);
- "prepare" tools create drafts only (a draft invoice has no number and can be deleted;
  an email draft is text for the owner to send with one tap) — nothing is issued, sent,
  paid or submitted by the agent;
- every tool call is logged on the conversation and in the audit log.
Figures always come from the tools (deterministic services), never from the model.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.assistant.providers import minimise
from locuvi.config import Settings
from locuvi.errors import DomainError
from locuvi.models import AgentConversation, Invoice, InvoiceStatus, Practice, utcnow
from locuvi.services import (
    bank,
    branding,
    checks,
    core,
    diary,
    documents,
    payments,
    pension,
    reports,
)

log = logging.getLogger(__name__)

MAX_STEPS = 10
MAX_TOOL_CHARS = 20_000


def _nullable(t: str, **extra: Any) -> dict[str, Any]:
    return {"anyOf": [{"type": t, **extra}, {"type": "null"}]}


def _tool(name: str, description: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
    props = props or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


MONTH = {"type": "string", "pattern": r"^\d{4}-\d{2}$"}
DATE = {"type": "string", "format": "date"}

TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_overview",
        "Today's summary: invoiced this month, outstanding total, tax-year "
        "totals, months ready to invoice, drafts, unpaid invoices and pension months due.",
    ),
    _tool(
        "run_checks",
        "Deterministic checks of all records: uninvoiced sessions, overdue "
        "invoices, duplicates/overlaps, pension and Form A items, unmatched bank payments, "
        "backups. Each finding has a kind, severity and parameters.",
    ),
    _tool("list_practices", "Practices on file with their usual rate and invoicing notes."),
    _tool(
        "list_sessions",
        "Diary sessions between two dates (inclusive), optionally one practice.",
        {"start": DATE, "end": DATE, "practice_id": _nullable("string")},
    ),
    _tool(
        "find_uninvoiced_sessions",
        "Worked sessions not yet on an invoice, grouped by practice and month, with totals.",
    ),
    _tool(
        "list_invoices",
        "Invoices, newest first. Filter by status (draft, issued, voided) "
        "and/or payment state (unpaid, part_paid, paid, overdue).",
        {
            "status": _nullable("string", enum=["draft", "issued", "voided"]),
            "payment": _nullable("string", enum=["unpaid", "part_paid", "paid", "overdue"]),
        },
    ),
    _tool(
        "get_invoice",
        "One invoice by its number (e.g. LOC-2026-0001): lines, totals, payments, payment "
        "state and correspondence (emails sent; linked inbox documents, readable with "
        "read_document).",
        {"number": {"type": "string"}},
    ),
    _tool(
        "financial_summary",
        "Tax-year report (UK, 6 April start): invoiced, received, "
        "outstanding, by month and by practice, self-assessment figures.",
        {"tax_year": _nullable("integer")},
    ),
    _tool(
        "pension_overview",
        "Pension months: Forms A (one per invoice, for work done that month, with signed "
        "count) and Form B (pensionable fees received that month, due by the 7th of the next "
        "month), submission and PCSE status.",
    ),
    _tool(
        "pension_month",
        "One month: Form A rows for work done in it (per invoice, with the 10-week deadline "
        "and Form A progress) and the Form B for fees received in it (items, totals, due "
        "date), with the PCSE comparison.",
        {"month": MONTH},
    ),
    _tool(
        "list_documents",
        "Inbox documents the owner added (booking emails, remittances, "
        "statements, forms). Optional search text.",
        {"query": _nullable("string")},
    ),
    _tool(
        "read_document",
        "Text of one inbox document (authorised by the owner by adding it).",
        {"document_id": {"type": "string"}},
    ),
    _tool(
        "bank_payments_to_match",
        "Credits from imported bank statements not yet matched to "
        "an invoice, with Locuvi's suggested match if any.",
    ),
    _tool(
        "prepare_invoice_draft",
        "Prepare a DRAFT invoice from the worked, uninvoiced "
        "sessions of one practice in one month. Drafts have no number and can be deleted; "
        "the owner reviews and issues it themselves.",
        {"practice_id": {"type": "string"}, "month": MONTH},
    ),
    _tool(
        "draft_email",
        "Draft (do not send) an email for an issued invoice: the invoice "
        "covering email, or a polite payment reminder. Returns text for the owner to "
        "review; the owner sends it from the invoice page.",
        {"number": {"type": "string"}, "kind": {"type": "string", "enum": ["invoice", "reminder"]}},
    ),
]

SYSTEM_PROMPT = """\
You are the administrative assistant inside Locuvi, a UK GP locum's own invoicing and records
app. You help the doctor (the owner) with locum admin: sessions, invoices, payments, NHS
pension Forms A/B, and correspondence.

How you work:
- Use the tools to look things up. Every figure you state must come from a tool result; never
  estimate or calculate money yourself beyond simple reading of the returned figures.
- Distinguish confirmed facts (from records) from assumptions or suggestions, and say when
  something can't be verified from the records (e.g. whether PCSE accepted a form).
- You cannot issue invoices, send email, record payments, submit pension forms or change bank
  details. You may prepare invoice drafts and draft emails; say clearly that they are drafts
  for the owner to review, and where to find them.
- When asked to check everything, run the checks, prioritise by urgency, and give a short
  list of next actions.
- Never include patient-identifiable information.
- Reply in British English, briefly and plainly. Use short bullet lists for several items.
  Money as £1,234.56; dates like 3 Oct 2026."""


def _money(v: Any) -> str | None:
    return str(v) if v is not None else None


def _inv_summary(inv: Invoice) -> dict[str, Any]:
    st = payments.payment_state(inv)
    return {
        "id": inv.id,
        "number": inv.invoice_number,
        "status": inv.status,
        "practice": (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name")
        or (inv.practice.name if inv.practice else None),
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "work": [
            inv.work_start_date.isoformat() if inv.work_start_date else None,
            inv.work_end_date.isoformat() if inv.work_end_date else None,
        ],
        "total": _money(inv.grand_total),
        "payment": st["state"],
        "outstanding": st["outstanding"],
        "days_overdue": st["days_overdue"],
    }


class Tools:
    """Executes tool calls against the service layer. Records drafts it creates."""

    def __init__(self, s: Session, settings: Settings) -> None:
        self.s, self.settings = s, settings
        self.created: list[dict[str, Any]] = []

    def run(self, name: str, args: dict[str, Any]) -> Any:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            raise DomainError("agent.unknown_tool", f"Unknown tool {name}.")
        return fn(**args)

    # read -------------------------------------------------------------------
    def t_get_overview(self) -> Any:
        ov = reports.today_overview(self.s)
        ov.pop("greeting_name", None)
        ov.pop("findings", None)
        return ov

    def t_run_checks(self) -> Any:
        found = checks.run_checks(self.s, self.settings)
        return {
            "counts": checks.summary_counts(found),
            "findings": [
                {"kind": f.kind, "severity": f.severity, "params": f.params} for f in found
            ],
        }

    def t_list_practices(self) -> Any:
        return [
            {
                "id": p.id,
                "name": p.name,
                "paid_per": "hour" if p.default_unit == "hours" else "session",
                "session_rate": _money(p.default_rate),
                "hourly_rate": _money(p.hourly_rate),
                "usual_hours": str(p.default_hours) if p.default_hours is not None else None,
                "rates_include_employer_pension": p.rate_includes_pension,
                "po_required": p.po_required,
                "invoice_instructions": p.invoice_instructions,
                "billing_email_set": bool(p.billing_email),
            }
            for p in self.s.scalars(select(Practice).where(Practice.is_archived.is_(False)))
        ]

    def t_list_sessions(self, start: str, end: str, practice_id: str | None) -> Any:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if (b - a).days > 400:
            raise DomainError("agent.range", "Choose a period of up to about a year.")
        rows = diary.list_sessions(self.s, a, b)
        return [
            {
                "date": w.date.isoformat(),
                "practice": w.practice.name,
                "unit": w.unit,
                "quantity": str(w.quantity),
                "rate": str(w.rate),
                "status": w.status,
                "invoiced": bool(w.invoice_id),
            }
            for w in rows
            if practice_id in (None, w.practice_id)
        ]

    def t_find_uninvoiced_sessions(self) -> Any:
        return diary.ready_to_invoice(self.s)

    def t_list_invoices(self, status: str | None, payment: str | None) -> Any:
        stmt = select(Invoice).order_by(Invoice.invoice_date.desc().nulls_last()).limit(200)
        if status:
            stmt = stmt.where(Invoice.status == status)
        out = [_inv_summary(i) for i in self.s.scalars(stmt)]
        return [i for i in out if payment in (None, i["payment"])][:100]

    def _by_number(self, number: str) -> Invoice:
        inv = self.s.scalars(
            select(Invoice).where(Invoice.invoice_number == number.strip())
        ).first()
        if inv is None:
            raise DomainError("agent.no_invoice", f"No invoice numbered {number}.")
        return inv

    def t_get_invoice(self, number: str) -> Any:
        inv = self._by_number(number)
        return {
            **_inv_summary(inv),
            "lines": [
                {
                    "date": ln.service_date.isoformat(),
                    "description": ln.description,
                    "quantity": str(ln.quantity),
                    "price": str(ln.unit_price),
                    "amount": str(ln.amount),
                }
                for ln in inv.lines
            ],
            "payments": [
                {"paid_on": p.paid_on.isoformat(), "amount": str(p.amount)} for p in inv.payments
            ],
            "employer_contribution": _money(inv.employer_contribution),
            "last_emailed": inv.last_emailed_at.isoformat() if inv.last_emailed_at else None,
            "correspondence": documents.correspondence(self.s, inv.id),
        }

    def t_financial_summary(self, tax_year: int | None) -> Any:
        year = tax_year or reports.tax_year_of(core.today_london())
        return reports.summary(self.s, year)

    def t_pension_overview(self) -> Any:
        return pension.overview(self.s)

    def t_pension_month(self, month: str) -> Any:
        fig = pension.month_figures(self.s, month)
        fig.pop("locum", None)  # personal identifiers are not needed
        return fig

    def t_list_documents(self, query: str | None) -> Any:
        return [
            {
                "id": d.id,
                "kind": d.kind,
                "title": d.title,
                "status": d.status,
                "added": d.created_at.date().isoformat(),
                "source": d.source,
            }
            for d in documents.list_docs(self.s, q=(query or None))[:50]
        ]

    def t_read_document(self, document_id: str) -> Any:
        d = documents.get(self.s, document_id)
        return {"title": d.title, "kind": d.kind, "text": minimise(d.text_content)[:15000]}

    def t_bank_payments_to_match(self) -> Any:
        return [
            bank.as_dict(t) for t in bank.listing(self.s) if t.status in {"suggested", "unmatched"}
        ][:100]

    # prepare (drafts only) ---------------------------------------------------
    def t_prepare_invoice_draft(self, practice_id: str, month: str) -> Any:
        inv = diary.invoice_month(self.s, practice_id, month)
        self.created.append(
            {
                "type": "invoice_draft",
                "invoice_id": inv.id,
                "practice": inv.practice.name if inv.practice else None,
                "month": month,
            }
        )
        core.audit(self.s, "agent.draft_invoice", invoice_id=inv.id, month=month)
        self.s.commit()
        return {
            "draft_invoice_id": inv.id,
            "total": _money(inv.grand_total),
            "note": "Draft only. The owner reviews and issues it in Invoices.",
        }

    def t_draft_email(self, number: str, kind: str) -> Any:
        from locuvi import mail

        inv = self._by_number(number)
        if inv.status != InvoiceStatus.issued:
            raise DomainError("agent.not_issued", "Only issued invoices can be emailed.")
        d = mail.draft_for(self.s, inv)
        if kind == "reminder":
            st = payments.payment_state(inv)
            d["subject"] = f"Reminder: {d['subject']}"
            d["body"] = (
                f"{d['body'].split(chr(10), 1)[0]}\n\n"  # same greeting as the invoice email
                f"I hope you are well. I'm writing about invoice {inv.invoice_number}, which "
                f"was due on {inv.due_date:%d %B %Y}. My records show "
                f"£{Decimal(st['outstanding'] or 0):,.2f} "
                "outstanding. I would be grateful if you could arrange payment, or let me know "
                "if there is any problem with the invoice.\n\nThe invoice is attached again for "
                "convenience.\n\n"
                + branding.signoff(
                    core.get_profile(self.s),
                    (inv.immutable_snapshot_json or {}).get("seller", {}).get("legal_name", ""),
                )
            )
        self.created.append(
            {
                "type": "email_draft",
                "invoice_id": inv.id,
                "kind": kind,
                "to": d.get("to"),
                "subject": d["subject"],
                "body": d["body"],
            }
        )
        return {
            "to": d.get("to"),
            "subject": d["subject"],
            "body": d["body"],
            "note": "Draft only — not sent. The owner sends it from the invoice page.",
        }


def _block_dict(b: Any) -> dict[str, Any]:
    if isinstance(b, dict):
        return b
    return b.to_dict() if hasattr(b, "to_dict") else dict(b)


def echo_content(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assistant content to send back next turn. After a server-side fallback, model-internal
    blocks that came before the last fallback marker are dropped (API rule); everything else is
    echoed unchanged, thinking blocks included."""
    idx = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
    if idx < 0:
        return blocks
    drop = {"thinking", "redacted_thinking", "tool_use"}
    return [b for i, b in enumerate(blocks) if i > idx or b.get("type") not in drop]


def _jsonable(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def ask(
    s: Session,
    settings: Settings,
    provider: Any,
    question: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """One owner question → tool loop → answer. Conversation history is kept for follow-ups."""
    question = (question or "").strip()[:4000]
    if not question:
        raise DomainError("agent.empty", "Ask a question first.")
    conv = s.get(AgentConversation, conversation_id) if conversation_id else None
    if conv is None:
        conv = AgentConversation(messages_json=[], steps_json=[], title=question[:120])
        s.add(conv)
        s.commit()  # a failing tool rolls back its own work, never the conversation
    messages: list[dict[str, Any]] = list(conv.messages_json or [])
    messages.append({"role": "user", "content": question})
    tools = Tools(s, settings)
    steps: list[dict[str, Any]] = []
    answer = ""
    for _ in range(MAX_STEPS):
        resp = provider.run_turn(system=SYSTEM_PROMPT, messages=messages, tools=TOOLS)
        if resp.stop_reason == "refusal":
            raise DomainError("assistant.refused", "The assistant declined this request.")
        content = [_block_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": echo_content(content)})
        uses = [b for b in content if b.get("type") == "tool_use"]
        if resp.stop_reason != "tool_use" or not uses:
            answer = "\n\n".join(b["text"] for b in content if b.get("type") == "text").strip()
            break
        results = []
        for u in uses:
            step = {"tool": u["name"], "input": u.get("input") or {}, "ok": True}
            try:
                out = tools.run(u["name"], dict(u.get("input") or {}))
                text = json.dumps(_jsonable(out))[:MAX_TOOL_CHARS]
                results.append({"type": "tool_result", "tool_use_id": u["id"], "content": text})
            except (DomainError, ValueError, TypeError) as exc:
                s.rollback()
                step["ok"] = False
                msg = getattr(exc, "message", None) or str(exc) or "error"
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": u["id"],
                        "content": f"Error: {msg}",
                        "is_error": True,
                    }
                )
            steps.append(step)
        messages.append({"role": "user", "content": results})
    else:
        answer = "I couldn't finish that within the step limit. Try a narrower question."
    conv = s.get(AgentConversation, conv.id) or conv
    conv.messages_json = _jsonable(messages)
    conv.steps_json = _jsonable(list(conv.steps_json or []) + steps)
    conv.updated_at = utcnow()
    core.audit(
        s,
        "agent.asked",
        conversation_id=conv.id,
        tools=[x["tool"] for x in steps],
        created=[c["type"] for c in tools.created],
        engine=provider.engine,
    )
    s.commit()
    return {
        "conversation_id": conv.id,
        "answer": answer,
        "steps": steps,
        "created": _jsonable(tools.created),
        "engine": provider.engine,
    }
