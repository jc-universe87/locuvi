"""Document inbox, the optional assistant and its proposals (/api/v1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.api import schemas as S
from locuvi.api.routes import DB, api, state
from locuvi.assistant import providers
from locuvi.errors import DomainError, NotFound
from locuvi.models import Document, Proposal
from locuvi.services import documents, proposals


def _doc_out(d: Document, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": d.id,
        "kind": d.kind,
        "title": d.title,
        "source": d.source,
        "filename": d.filename,
        "content_type": d.content_type,
        "size": d.size,
        "status": d.status,
        "practice_id": d.practice_id,
        "invoice_id": d.invoice_id,
        "has_file": bool(d.stored_name),
        "has_text": bool(d.text_content.strip()),
        "excerpt": " ".join(d.text_content.split())[:160],
        "created_at": d.created_at,
        "deleted": d.deleted_at is not None,
    }
    if full:
        out["text"] = d.text_content
    return out


def _provider(request: Request, s: Session) -> providers.Provider | None:
    factory = getattr(state(request), "ai_provider_factory", None)
    if factory is not None:  # tests inject a fake provider; never the real API
        return factory(s)
    return providers.provider_for(s, state(request).settings, state(request).secrets)


# ----------------------------------------------------------------------- inbox


@api.get("/documents")
def list_documents(s: DB, status: str | None = None, q: str | None = None) -> dict[str, Any]:
    if status not in (None, "new", "done"):
        raise DomainError("document.bad_status", "Unknown status.")
    docs = documents.list_docs(s, status=status, q=(q or "")[:100] or None)
    return {"documents": [_doc_out(d) for d in docs], "new": documents.new_count(s)}


@api.post("/documents", status_code=201)
def upload_document(
    request: Request,
    s: DB,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    data = file.file.read(documents.MAX_BYTES + 1)
    doc = documents.add_upload(
        s, state(request).settings, file.filename or "document", file.content_type, data
    )
    if kind in documents.KINDS and doc.kind != kind:
        documents.update(s, doc, kind=kind)
    return _doc_out(doc, full=True)


@api.post("/documents/paste", status_code=201)
def paste_document(body: S.PasteIn, s: DB) -> dict[str, Any]:
    return _doc_out(documents.add_paste(s, body.text, body.kind), full=True)


@api.get("/documents/{doc_id}")
def get_document(doc_id: str, s: DB) -> dict[str, Any]:
    doc = documents.get(s, doc_id)
    out = _doc_out(doc, full=True)
    out["proposals"] = [
        proposals.as_dict(p)
        for p in s.scalars(
            select(Proposal)
            .where(Proposal.document_id == doc.id)
            .order_by(Proposal.created_at.desc())
        )
    ]
    return out


@api.get("/documents/{doc_id}/file")
def document_file(doc_id: str, request: Request, s: DB) -> FileResponse:
    doc = documents.get(s, doc_id)
    path = documents.file_path(state(request).settings, doc)
    if path is None:
        raise NotFound("document.no_file", "This document has no file.")
    return FileResponse(
        path,
        media_type=doc.content_type or "application/octet-stream",
        filename=doc.filename or path.name,
        content_disposition_type="attachment",
    )


@api.patch("/documents/{doc_id}")
def patch_document(doc_id: str, body: S.DocumentPatch, s: DB) -> dict[str, Any]:
    doc = documents.get(s, doc_id)
    return _doc_out(documents.update(s, doc, **body.model_dump(exclude_unset=True)))


@api.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, s: DB) -> Response:
    documents.trash(s, documents.get(s, doc_id))
    return Response(status_code=204)


@api.post("/documents/{doc_id}/restore")
def restore_document(doc_id: str, s: DB) -> dict[str, Any]:
    return _doc_out(documents.restore(s, documents.get(s, doc_id, include_deleted=True)))


@api.post("/documents/{doc_id}/read", status_code=201)
def read_document(
    doc_id: str, request: Request, s: DB, body: S.ReadDocumentIn | None = None
) -> dict[str, Any]:
    doc = documents.get(s, doc_id)
    prop = proposals.read_booking(
        s,
        state(request).settings,
        doc,
        _provider(request, s),
        send_attachment=bool(body and body.send_attachment),
    )
    return proposals.as_dict(prop)


@api.post("/assistant/booking", status_code=201)
def paste_booking(body: S.PasteIn, request: Request, s: DB) -> dict[str, Any]:
    """Paste a booking email: keep it in the inbox and propose the sessions in one step."""
    doc = documents.add_paste(s, body.text, "booking")
    prop = proposals.read_booking(s, state(request).settings, doc, _provider(request, s))
    return {"document": _doc_out(doc), "proposal": proposals.as_dict(prop)}


# ------------------------------------------------------------------- proposals


@api.get("/proposals")
def list_proposals(s: DB) -> list[dict[str, Any]]:
    return [proposals.as_dict(p) for p in proposals.pending(s)]


@api.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, s: DB) -> dict[str, Any]:
    return proposals.as_dict(proposals.get(s, proposal_id))


@api.post("/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: str, body: S.ProposalAcceptIn, s: DB) -> dict[str, Any]:
    choices = [c.model_dump(exclude_none=True, mode="json") for c in body.items]
    return proposals.as_dict(proposals.accept(s, proposals.get(s, proposal_id), choices))


@api.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, s: DB) -> dict[str, Any]:
    return proposals.as_dict(proposals.reject(s, proposals.get(s, proposal_id)))


@api.post("/proposals/{proposal_id}/undo")
def undo_proposal(proposal_id: str, s: DB) -> dict[str, Any]:
    return proposals.as_dict(proposals.undo(s, proposals.get(s, proposal_id)))


# ------------------------------------------------------------------- settings


@api.get("/settings/assistant")
def get_assistant(request: Request, s: DB) -> dict[str, Any]:
    return providers.config_public(providers.get_config(s), state(request).settings)


@api.put("/settings/assistant")
def put_assistant(body: S.AssistantIn, request: Request, s: DB) -> dict[str, Any]:
    cfg = providers.save_config(
        s,
        state(request).secrets,
        enabled=body.enabled,
        api_key=body.api_key,
        clear_key=body.clear_key,
        weekly_brief=body.weekly_brief,
        provider=body.provider,
        model=body.model,
        base_url=body.base_url,
    )
    return providers.config_public(cfg, state(request).settings)


@api.post("/settings/assistant/check")
def check_assistant(request: Request, s: DB) -> dict[str, Any]:
    factory = getattr(state(request), "ai_model_lister", None)  # tests: fake provider
    return providers.check_key(s, state(request).settings, state(request).secrets, factory)


# ------------------------------------------------------------------ mail folders


@api.get("/settings/mailboxes")
def list_mailboxes(s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    return {"accounts": [mailbox.account_public(a) for a in mailbox.list_accounts(s)]}


@api.post("/settings/mailboxes", status_code=201)
def add_mailbox(body: S.MailboxIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    acc = mailbox.create_account(s, state(request).secrets, body.model_dump())
    return mailbox.account_public(acc)


@api.put("/settings/mailboxes/{account_id}")
def put_mailbox(account_id: int, body: S.MailboxIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    acc = mailbox.get_account(s, account_id)
    acc = mailbox.save_account(s, state(request).secrets, acc, body.model_dump())
    return mailbox.account_public(acc)


@api.delete("/settings/mailboxes/{account_id}")
def remove_mailbox(account_id: int, s: DB) -> dict[str, Any]:
    """Remove an account (restore it from Recently deleted until it is purged after 30 days)."""
    from locuvi.services import mailbox

    return mailbox.account_public(mailbox.remove_account(s, account_id))


@api.post("/settings/mailboxes/{account_id}/restore")
def restore_mailbox(account_id: int, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    return mailbox.account_public(mailbox.restore_account(s, account_id))


@api.post("/settings/mailboxes/{account_id}/folders")
def mailbox_folders(account_id: int, request: Request, s: DB) -> dict[str, Any]:
    """Connect with the saved details and list folders, so the owner can tick which to read."""
    from locuvi.services import mailbox

    acc = mailbox.get_account(s, account_id)
    factory = _ms(request) if acc.provider == "microsoft" else _imap(request)
    folders = mailbox.list_folders(
        s, state(request).settings, state(request).secrets, account_id, factory=factory
    )
    return {"folders": folders}


@api.post("/settings/mailboxes/{account_id}/microsoft/start")
def mailbox_ms_start(
    account_id: int, body: S.MicrosoftSignInIn, request: Request, s: DB
) -> dict[str, Any]:
    """Begin a Microsoft sign-in: returns a short code to enter at microsoft.com/devicelogin."""
    from locuvi.services import mailbox

    return mailbox.ms_start(s, account_id, body.client_id, body.tenant, _ms(request))


@api.post("/settings/mailboxes/{account_id}/microsoft/poll")
def mailbox_ms_poll(account_id: int, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    r = mailbox.ms_poll(s, state(request).secrets, account_id, _ms(request))
    return {**r, "account": mailbox.account_public(mailbox.get_account(s, account_id))}


@api.delete("/settings/mailboxes/{account_id}/microsoft")
def mailbox_ms_sign_out(account_id: int, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    return mailbox.account_public(mailbox.ms_sign_out(s, account_id))


@api.post("/mailbox/scan")
def mailbox_scan(request: Request, s: DB) -> dict[str, Any]:
    """Check every switched-on email account now."""
    from locuvi.services import mailbox

    return mailbox.scan(
        s,
        state(request).settings,
        state(request).secrets,
        provider=_provider(request, s),
        factory=_imap(request),
        transport=_ms(request),
    )


def _imap(request: Request) -> Any:
    """Test hook: a fake IMAP server factory."""
    return getattr(state(request), "imap_factory", None)


def _ms(request: Request) -> Any:
    """Test hook: a fake Microsoft transport."""
    return getattr(state(request), "ms_transport", None)


# ------------------------------------------------------------------------ bank


@api.post("/bank/import", status_code=201)
def bank_import(s: DB, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    from locuvi.services import bank

    data = file.file.read(bank.MAX_BYTES + 1)
    return bank.import_statement(s, file.filename or "statement.csv", data)


@api.get("/bank/transactions")
def bank_transactions(s: DB, status: str | None = None) -> dict[str, Any]:
    from locuvi.services import bank

    if status not in (None, "suggested", "unmatched", "matched", "ignored"):
        raise DomainError("bank.bad_status", "Unknown status.")
    return {
        "transactions": [bank.as_dict(t) for t in bank.listing(s, status)],
        "counts": bank.summary(s),
    }


@api.post("/bank/transactions/accept-all")
def bank_accept_all(s: DB) -> dict[str, Any]:
    from locuvi.services import bank

    return {"recorded": bank.accept_all(s), "counts": bank.summary(s)}


@api.post("/bank/transactions/{tx_id}/accept")
def bank_accept(tx_id: str, body: S.BankAcceptIn, s: DB) -> dict[str, Any]:
    from locuvi.services import bank

    tx = bank.get(s, tx_id)
    bank.accept(s, tx, body.invoice_ids)
    return bank.as_dict(tx)


@api.post("/bank/transactions/{tx_id}/ignore")
def bank_ignore(tx_id: str, s: DB) -> dict[str, Any]:
    from locuvi.services import bank

    tx = bank.get(s, tx_id)
    bank.ignore(s, tx)
    return bank.as_dict(tx)


@api.post("/bank/transactions/{tx_id}/undo")
def bank_undo(tx_id: str, s: DB) -> dict[str, Any]:
    from locuvi.services import bank

    tx = bank.get(s, tx_id)
    bank.undo(s, tx)
    return bank.as_dict(tx)


# ----------------------------------------------------------------------- agent


@api.post("/assistant/ask")
def agent_ask(body: S.AgentAskIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.assistant import agent

    provider = _provider(request, s)
    if provider is None or not hasattr(provider, "run_turn"):
        raise DomainError("assistant.off", "Turn on the assistant in Settings first.")
    if not getattr(provider, "supports_agent", True):
        raise DomainError(
            "assistant.no_agent",
            "This AI company can read bookings but can't answer questions.",
        )
    return agent.ask(s, state(request).settings, provider, body.question, body.conversation_id)


@api.get("/assistant/conversations")
def agent_conversations(s: DB) -> list[dict[str, Any]]:
    from locuvi.models import AgentConversation

    rows = s.scalars(
        select(AgentConversation).order_by(AgentConversation.updated_at.desc()).limit(30)
    )
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at,
             "tools_used": len(c.steps_json or [])} for c in rows]  # fmt: skip


@api.get("/assistant/conversations/{conversation_id}")
def agent_conversation(conversation_id: str, s: DB) -> dict[str, Any]:
    """Readable transcript: the owner's questions and the assistant's answers, plus tool log."""
    from locuvi.models import AgentConversation

    c = s.get(AgentConversation, conversation_id)
    if c is None:
        raise NotFound("agent.not_found", "Conversation not found.")
    turns = []
    for m in c.messages_json or []:
        if m["role"] == "user" and isinstance(m["content"], str):
            turns.append({"role": "user", "text": m["content"]})
        elif m["role"] == "assistant":
            text = "\n\n".join(b.get("text", "") for b in m["content"] if b.get("type") == "text")
            if text.strip() and not any(b.get("type") == "tool_use" for b in m["content"]):
                turns.append({"role": "assistant", "text": text.strip()})
    return {"id": c.id, "title": c.title, "turns": turns, "steps": c.steps_json or []}


# ------------------------------------------------------- connected agents (Bevro)


@api.get("/settings/agents")
def list_agent_tokens(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.api import mcp
    from locuvi.models import AgentToken

    rows = s.scalars(select(AgentToken).order_by(AgentToken.created_at.desc()))
    return {"endpoint_path": "/mcp", "tokens": [mcp.token_public(t) for t in rows]}


@api.post("/settings/agents", status_code=201)
def create_agent_token(body: S.AgentTokenIn, s: DB) -> dict[str, Any]:
    """Returns the token once; only its hash is kept."""
    from locuvi.api import mcp

    row, token = mcp.create_token(s, body.name, body.allow_drafts)
    return {**mcp.token_public(row), "token": token}


@api.delete("/settings/agents/{token_id}", status_code=204)
def revoke_agent_token(token_id: str, s: DB) -> Response:
    from locuvi.api import mcp

    mcp.revoke_token(s, token_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- calendar feed

feeds = APIRouter()


@feeds.get("/calendar/{token}.ics", include_in_schema=False)
def calendar_ics(token: str, request: Request) -> Response:
    """Public by secret link (calendar apps can't sign in). Unknown link → 404."""
    from locuvi import db, profiles
    from locuvi.services import calendar

    if len(token) > 100:
        raise NotFound("calendar.not_found", "Not found.")
    pid = profiles.find(request.app.state.settings, lambda s: calendar.lookup(s, token) is not None)
    if pid is None:
        raise NotFound("calendar.not_found", "Not found.")
    with db.use_profile(pid), db.new_session() as s:
        feed = calendar.lookup(s, token)
        if feed is None:
            raise NotFound("calendar.not_found", "Not found.")
        body = calendar.render(s, feed)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="locum.ics"',
        },
    )


@api.get("/settings/calendar")
def get_calendar(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import calendar

    return calendar.public(calendar.get(s), state(request).secrets)


@api.put("/settings/calendar")
def put_calendar(body: S.CalendarIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import calendar

    if body.enabled:
        calendar.enable(s, state(request).secrets, include_fees=body.include_fees,
                        regenerate=body.regenerate)  # fmt: skip
    else:
        calendar.disable(s)
    return calendar.public(calendar.get(s), state(request).secrets)
