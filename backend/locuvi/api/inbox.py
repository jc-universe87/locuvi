"""Document inbox, the optional assistant and its proposals (/api/v1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import File, Form, Request, Response, UploadFile
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
def read_document(doc_id: str, request: Request, s: DB) -> dict[str, Any]:
    doc = documents.get(s, doc_id)
    prop = proposals.read_booking(s, state(request).settings, doc, _provider(request, s))
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
    )
    return providers.config_public(cfg, state(request).settings)


# ------------------------------------------------------------------ mail folders


@api.get("/settings/mailbox")
def get_mailbox(s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    return mailbox.config_public(mailbox.get_config(s))


@api.put("/settings/mailbox")
def put_mailbox(body: S.MailboxIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    cfg = mailbox.save_config(s, state(request).secrets, body.model_dump())
    return mailbox.config_public(cfg)


@api.post("/settings/mailbox/folders")
def mailbox_folders(request: Request, s: DB) -> dict[str, Any]:
    """Connect with the saved details and list folders, so the owner can tick which to read."""
    from locuvi.services import mailbox

    folders = mailbox.list_folders(
        s, state(request).settings, state(request).secrets,
        factory=getattr(state(request), "imap_factory", None),
    )  # fmt: skip
    return {"folders": folders}


@api.post("/mailbox/scan")
def mailbox_scan(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import mailbox

    return mailbox.scan(
        s,
        state(request).settings,
        state(request).secrets,
        provider=_provider(request, s),
        factory=getattr(state(request), "imap_factory", None),
    )


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
