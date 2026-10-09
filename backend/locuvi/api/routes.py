"""REST API /api/v1 (engineering/API.md)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from locuvi import __version__
from locuvi.api import schemas as S
from locuvi.api.auth import COOKIE, SessionManager, Unauthorized
from locuvi.db import get_session
from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import Document, Invoice, InvoiceEvent, PensionPolicy, Practice
from locuvi.services import core, diary, payments, pension, reports
from locuvi.services import invoices as svc
from locuvi.storage.local import resolve, sha256_file
from locuvi.webdav import archive

DB = Annotated[Session, Depends(get_session)]


def state(request: Request) -> Any:
    return request.app.state


def require_auth(request: Request) -> None:
    sm: SessionManager = request.app.state.sessions
    sm.enforce(request)


public = APIRouter(prefix="/api/v1")
api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])


# ------------------------------------------------------------------ auth/health


@public.get("/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    sm: SessionManager = request.app.state.sessions
    token = request.cookies.get(COOKIE)
    ok = sm.authenticated(request)
    return {
        "authenticated": ok,
        "auth_mode": sm.mode,
        "csrf_token": sm.csrf_for(token) if ok else None,
        "version": __version__,
    }


@public.post("/auth/login")
def login(body: S.LoginIn, request: Request, response: Response) -> dict[str, Any]:
    sm: SessionManager = request.app.state.sessions
    if sm.mode != "password":
        return {"authenticated": True, "csrf_token": sm.csrf_for(None)}
    if not sm.check_password(body.password):
        raise Unauthorized("auth.invalid_password", "That password is not correct.")
    token = sm.issue_token()
    st = request.app.state.settings
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=st.cookie_secure,
        samesite="strict",
        max_age=st.session_hours * 3600,
        path="/",
    )
    return {"authenticated": True, "csrf_token": sm.csrf_for(token)}


@api.post("/auth/password")
def change_password(
    body: S.PasswordChangeIn, request: Request, response: Response, s: DB
) -> dict[str, Any]:
    """Change the owner password in the app. Every other session is signed out."""
    from locuvi.api.auth import hash_password
    from locuvi.models import AuthConfig, utcnow

    sm: SessionManager = request.app.state.sessions
    if sm.mode != "password":
        raise DomainError("auth.gateway_mode", "Sign-in is handled by your gateway.")
    if not sm.check_password(body.current):
        raise Unauthorized("auth.invalid_password", "That password is not correct.")
    if body.new == body.current:
        raise DomainError("auth.same_password", "Choose a different password.")
    cfg = s.get(AuthConfig, 1) or AuthConfig(id=1, session_epoch=0)
    s.add(cfg)
    cfg.password_hash = hash_password(body.new)
    cfg.session_epoch = (cfg.session_epoch or 0) + 1
    cfg.changed_at = utcnow()
    core.audit(s, "auth.password_changed")
    s.commit()
    sm.set_password_hash(cfg.password_hash, cfg.session_epoch)
    token = sm.issue_token()  # keep this device signed in
    st = request.app.state.settings
    response.set_cookie(COOKIE, token, httponly=True, secure=st.cookie_secure,
                        samesite="strict", max_age=st.session_hours * 3600, path="/")  # fmt: skip
    return {"ok": True, "csrf_token": sm.csrf_for(token)}


@public.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@public.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@public.get("/health/ready")
def ready(request: Request, s: DB, response: Response) -> dict[str, Any]:
    s.execute(select(1))
    integrity = request.app.state.integrity
    ok = integrity.get("ok", False)
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "integrity": integrity}


# --------------------------------------------------------------------- settings


def _mask(acct: str) -> str:
    return f"••••{acct[-4:]}" if acct else ""


def _profile_out(p: Any) -> dict[str, Any]:
    return S.ProfileOut(
        legal_name=p.legal_name,
        trading_name=p.trading_name,
        designation=p.designation,
        address_lines=p.address_lines,
        postcode=p.postcode,
        email=p.email,
        phone=p.phone,
        bank_account_holder=p.bank_account_holder,
        bank_sort_code=p.bank_sort_code,
        bank_account_number_masked=_mask(p.bank_account_number),
        bank_account_number_set=bool(p.bank_account_number),
        vat_status=p.vat_status,
        payment_terms_days=p.payment_terms_days,
        pension_default_enabled=p.pension_default_enabled,
        professional_number=p.professional_number,
        pension_ref=p.pension_ref,
        employee_rate=str(p.employee_rate) if p.employee_rate is not None else None,
        setup_completed=p.setup_completed,
        digest_enabled=p.digest_enabled,
        accounting_basis=p.accounting_basis or "cash",
        last_digest_sent_at=p.last_digest_sent_at.isoformat() if p.last_digest_sent_at else None,
    ).model_dump()


@api.get("/settings/profile")
def get_profile(s: DB) -> dict[str, Any]:
    return _profile_out(core.get_profile(s))


@api.put("/settings/profile")
@api.patch("/settings/profile")
def put_profile(body: S.ProfileIn, s: DB) -> dict[str, Any]:
    """Partial update: only the fields sent are changed (autosave-friendly)."""
    p = core.get_profile(s)
    data = body.model_dump(exclude_unset=True)
    acct = data.pop("bank_account_number", None)
    nullable = {"trading_name", "phone", "professional_number", "pension_ref"}
    for k, v in data.items():
        if k in {"setup_completed", "digest_enabled", "accounting_basis"} and v is None:
            continue
        if k == "employee_rate":
            v = Decimal(v) if v not in (None, "") else None
            if v is not None and not (Decimal("0") <= v < Decimal("1")):
                raise DomainError(
                    "profile.employee_rate_range",
                    "Enter your tier as a fraction, e.g. 0.098 for 9.8%.",
                )
        elif isinstance(v, str):
            v = v.strip()
            if k in nullable:
                v = v or None
        elif v is None and k not in nullable:
            continue
        setattr(p, k, v)
    if acct is not None:
        p.bank_account_number = acct
    core.audit(s, "settings.profile_saved", bank_changed=acct is not None)
    s.commit()
    return _profile_out(p)


def _numbering_out(seq: Any) -> dict[str, Any]:
    return {
        "prefix": seq.prefix,
        "next_number": seq.next_number,
        "padding": seq.padding,
        "preview": core.format_number(seq.prefix, seq.next_number, seq.padding),
    }


@api.get("/settings/numbering")
def get_numbering(s: DB) -> dict[str, Any]:
    return _numbering_out(core.get_sequence(s))


@api.put("/settings/numbering")
def put_numbering(body: S.NumberingIn, s: DB) -> dict[str, Any]:
    candidate = core.format_number(body.prefix, body.next_number, body.padding)
    if s.scalars(select(Invoice.id).where(Invoice.invoice_number == candidate)).first():
        raise Conflict(
            "sequence.number_taken",
            f"{candidate} has already been used. Choose a higher next number.",
            number=candidate,
        )
    seq = core.get_sequence(s)
    seq.prefix, seq.next_number, seq.padding = body.prefix, body.next_number, body.padding
    core.audit(s, "settings.numbering_saved", prefix=body.prefix, next_number=body.next_number)
    s.commit()
    return _numbering_out(seq)


def _policy_out(s: Session, p: PensionPolicy) -> dict[str, Any]:
    in_use = (
        s.scalars(
            select(Invoice.id).where(Invoice.pension_policy_id == p.id, Invoice.status != "draft")
        ).first()
        is not None
    )
    return S.PolicyOut(
        id=p.id,
        effective_from=p.effective_from,
        employer_rate=str(p.employer_rate),
        pensionable_fraction=str(p.pensionable_fraction),
        label=p.label,
        source_note=p.source_note,
        in_use=in_use,
    ).model_dump()


@api.get("/settings/pension-policies")
def list_policies(s: DB) -> list[dict[str, Any]]:
    return [_policy_out(s, p) for p in core.all_policies(s)]


@api.post("/settings/pension-policies", status_code=201)
def add_policy(body: S.PolicyIn, s: DB) -> dict[str, Any]:
    rate, frac = Decimal(body.employer_rate), Decimal(body.pensionable_fraction)
    if not (Decimal("0") < rate < Decimal("1")):
        raise DomainError("policy.rate_range", "Enter the rate as a fraction, e.g. 0.1438.")
    if not (Decimal("0") < frac <= Decimal("1")):
        raise DomainError("policy.fraction_range", "Pensionable fraction must be in (0, 1].")
    if s.scalars(
        select(PensionPolicy).where(PensionPolicy.effective_from == body.effective_from)
    ).first():
        raise Conflict("policy.date_taken", "A rate already starts on that date.")
    p = PensionPolicy(
        effective_from=body.effective_from,
        employer_rate=rate,
        pensionable_fraction=frac,
        label=body.label.strip(),
        source_note=body.source_note.strip(),
    )
    s.add(p)
    core.audit(
        s,
        "settings.policy_added",
        effective_from=body.effective_from.isoformat(),
        employer_rate=str(rate),
    )
    s.commit()
    return _policy_out(s, p)


@api.delete("/settings/pension-policies/{policy_id}", status_code=204)
def delete_policy(policy_id: str, s: DB) -> Response:
    p = s.get(PensionPolicy, policy_id)
    if p is None:
        raise NotFound("policy.not_found", "Rate not found.")
    if _policy_out(s, p)["in_use"]:
        raise Conflict("policy.in_use", "This rate is used by issued invoices and is kept.")
    for inv in s.scalars(select(Invoice).where(Invoice.pension_policy_id == p.id)):
        inv.pension_policy_id = None
    s.delete(p)
    core.audit(s, "settings.policy_deleted", effective_from=p.effective_from.isoformat())
    s.commit()
    return Response(status_code=204)


# -------------------------------------------------------------------- practices


def _practice_out(p: Practice) -> dict[str, Any]:
    return S.PracticeOut(
        id=p.id,
        name=p.name,
        billing_address=p.billing_address,
        billing_email=p.billing_email,
        contact_name=p.contact_name,
        reference=p.reference,
        default_rate=str(p.default_rate) if p.default_rate is not None else None,
        default_unit=p.default_unit,
        default_pensionable=p.default_pensionable,
        rate_includes_pension=p.rate_includes_pension,
        default_payment_terms_days=p.default_payment_terms_days,
        is_archived=p.is_archived,
        practice_code=p.practice_code,
        po_required=p.po_required,
        invoice_instructions=p.invoice_instructions,
        form_a_signatory=p.form_a_signatory,
    ).model_dump()


def _apply_practice(p: Practice, data: dict[str, Any]) -> None:
    if "name" in data and not (data["name"] or "").strip():
        raise DomainError("practice.name_required", "Enter the practice name.")
    for k, v in data.items():
        if k == "default_rate":
            v = Decimal(v) if v not in (None, "") else None
        elif isinstance(v, str):
            v = v.strip()
            if k in {
                "billing_email",
                "contact_name",
                "reference",
                "practice_code",
                "invoice_instructions",
                "form_a_signatory",
            }:
                v = v or None
        if v is None and k in {
            "po_required",
            "is_archived",
            "default_pensionable",
            "rate_includes_pension",
            "default_unit",
        }:
            continue
        setattr(p, k, v)


@api.get("/practices")
def list_practices(s: DB, include_archived: bool = False) -> list[dict[str, Any]]:
    q = select(Practice).order_by(func.lower(Practice.name))
    if not include_archived:
        q = q.where(Practice.is_archived.is_(False))
    return [_practice_out(p) for p in s.scalars(q)]


@api.post("/practices", status_code=201)
def create_practice(body: S.PracticeIn, s: DB) -> dict[str, Any]:
    p = Practice(name=body.name.strip())
    _apply_practice(p, body.model_dump())
    s.add(p)
    s.commit()
    return _practice_out(p)


@api.get("/practices/{practice_id}")
def get_practice(practice_id: str, s: DB) -> dict[str, Any]:
    p = s.get(Practice, practice_id)
    if p is None:
        raise NotFound("practice.not_found", "Practice not found.")
    return _practice_out(p)


@api.patch("/practices/{practice_id}")
def patch_practice(practice_id: str, body: S.PracticePatch, s: DB) -> dict[str, Any]:
    p = s.get(Practice, practice_id)
    if p is None:
        raise NotFound("practice.not_found", "Practice not found.")
    _apply_practice(p, body.model_dump(exclude_unset=True))
    s.commit()
    return _practice_out(p)


# --------------------------------------------------------------------- invoices


def _lines(body_lines: list[S.LineIn]) -> list[svc.LineData]:
    out = []
    for ln in body_lines:
        q, price = ln.as_decimals()
        out.append(svc.LineData(ln.service_date, ln.description, ln.unit, q, price, ln.pensionable))
    return out


def _s(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _summary(s: Session, inv: Invoice) -> dict[str, Any]:
    practice_name = (
        inv.immutable_snapshot_json["bill_to"]["name"]
        if inv.immutable_snapshot_json
        else (inv.practice.name if inv.practice else None)
    )
    return {
        "id": inv.id,
        "status": inv.status,
        "invoice_number": inv.invoice_number,
        "practice_id": inv.practice_id,
        "practice_name": practice_name,
        "invoice_date": inv.invoice_date,
        "due_date": inv.due_date,
        "work_start_date": inv.work_start_date,
        "work_end_date": inv.work_end_date,
        "grand_total": _s(inv.grand_total),
        "archive": archive.archive_status(s, inv),
        "payment": payments.payment_state(inv),
        "last_emailed_at": inv.last_emailed_at,
        "updated_at": inv.updated_at,
    }


def _analysis_out(a: svc.Analysis) -> dict[str, Any]:
    return {
        "totals": a.totals.as_strings(),
        "blocking": [i.as_dict() for i in a.blocking],
        "warnings": [i.as_dict() for i in a.warnings],
        "work_start_date": a.work_start,
        "work_end_date": a.work_end,
        "policy": (
            {
                "id": a.policy.id,
                "label": a.policy.label,
                "effective_from": a.policy.effective_from,
                "employer_rate": str(a.policy.employer_rate),
                "pensionable_fraction": str(a.policy.pensionable_fraction),
            }
            if a.policy
            else None
        ),
    }


def _correspondence(s: Session, invoice_id: str) -> list[dict[str, Any]]:
    from locuvi.services import documents

    return documents.correspondence(s, invoice_id)  # type: ignore[return-value]


def _detail(s: Session, inv: Invoice) -> dict[str, Any]:
    out = _summary(s, inv)
    out.update(
        {
            "reference": inv.reference,
            "notes": inv.notes,
            "pension_enabled": inv.pension_enabled,
            "currency": inv.currency,
            "issued_at": inv.issued_at,
            "voided_at": inv.voided_at,
            "void_reason": inv.void_reason,
            "local_pdf_sha256": inv.local_pdf_sha256,
            "local_pdf_size": inv.local_pdf_size,
            "duplicated_from_id": inv.duplicated_from_id,
            "payments": [
                {
                    "id": p.id,
                    "paid_on": p.paid_on,
                    "amount": str(p.amount),
                    "method": p.method,
                    "reference": p.reference,
                }
                for p in inv.payments
            ],
            "lines": [
                {
                    "id": ln.id,
                    "service_date": ln.service_date,
                    "description": ln.description,
                    "unit": ln.unit,
                    "quantity": str(ln.quantity),
                    "unit_price": str(ln.unit_price),
                    "amount": str(ln.amount),
                    "pensionable": ln.pensionable,
                }
                for ln in inv.lines
            ],
            "events": [
                {"timestamp": e.timestamp, "event_type": e.event_type, "metadata": e.metadata_json}
                for e in s.scalars(
                    select(InvoiceEvent)
                    .where(InvoiceEvent.invoice_id == inv.id)
                    .order_by(InvoiceEvent.timestamp)
                )
            ],
            "correspondence": _correspondence(s, inv.id),
            "credit_notes": [
                {
                    "id": c.id,
                    "number": c.number,
                    "credit_date": c.credit_date,
                    "reason": c.reason,
                    "grand_total": str(c.grand_total),
                    "line_ids": c.line_ids,
                }
                for c in inv.credit_notes
            ],
        }
    )
    if inv.status == "draft":
        a = svc.analyse(
            s,
            lines=inv.lines,
            pension_enabled=inv.pension_enabled,
            practice=inv.practice,
            for_issue=True,
            reference=inv.reference,
        )
        out["analysis"] = _analysis_out(a)
    else:
        snap = inv.immutable_snapshot_json or {}
        out["snapshot"] = {k: snap.get(k) for k in ("seller", "bill_to", "totals", "pension")}
        out["snapshot"]["bank"] = {
            **(snap.get("bank") or {}),
            "account_number": _mask((snap.get("bank") or {}).get("account_number", "")),
        }
    return out


@api.get("/invoices")
def list_invoices(
    s: DB,
    status: str | None = None,
    practice_id: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    payment: str | None = None,
) -> dict[str, Any]:
    stmt = select(Invoice).outerjoin(Practice, Invoice.practice_id == Practice.id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if practice_id:
        stmt = stmt.where(Invoice.practice_id == practice_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Invoice.invoice_number.ilike(like),
                Practice.name.ilike(like),
                # Issued invoices show the frozen billed-to name; search it too.
                func.json_extract(Invoice.immutable_snapshot_json, "$.bill_to.name").ilike(like),
                Invoice.reference.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(func.coalesce(Invoice.work_end_date, Invoice.invoice_date) >= date_from)
    if date_to:
        stmt = stmt.where(func.coalesce(Invoice.work_start_date, Invoice.invoice_date) <= date_to)
    if payment:
        # Payment state is derived; filter in Python (single-user data volumes).
        wanted = set(payment.split(","))
        ids = [i.id for i in s.scalars(stmt) if payments.payment_state(i)["state"] in wanted]
        stmt = select(Invoice).where(Invoice.id.in_(ids))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.scalars(
        stmt.order_by(
            Invoice.status != "draft", Invoice.issued_at.desc(), Invoice.updated_at.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique()
    return {
        "items": [_summary(s, i) for i in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _save(s: Session, inv: Invoice | None, body: S.InvoiceIn) -> Invoice:
    fields = body.model_fields_set
    kw: dict[str, Any] = {}
    for name in ("practice_id", "invoice_date", "due_date", "reference", "notes"):
        if name in fields:
            kw[name] = getattr(body, name)
    if "pension_enabled" in fields and body.pension_enabled is not None:
        kw["pension_enabled"] = body.pension_enabled
    if "lines" in fields and body.lines is not None:
        kw["lines"] = _lines(body.lines)
    return svc.save_draft(s, inv, **kw)


@api.post("/invoices", status_code=201)
def create_invoice(body: S.InvoiceIn, s: DB) -> dict[str, Any]:
    return _detail(s, _save(s, None, body))


@api.post("/invoices/calculate")
def calculate(body: S.CalculateIn, s: DB) -> dict[str, Any]:
    lines = _lines(body.lines)
    for i, ln in enumerate(lines):
        svc.validate_line(ln, i)
    practice = s.get(Practice, body.practice_id) if body.practice_id else None
    a = svc.analyse(
        s,
        lines=lines,
        pension_enabled=body.pension_enabled,
        practice=practice,
        reference=body.reference,
    )
    return _analysis_out(a)


@api.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, s: DB) -> dict[str, Any]:
    return _detail(s, svc.get_invoice(s, invoice_id))


@api.patch("/invoices/{invoice_id}")
def patch_invoice(invoice_id: str, body: S.InvoiceIn, s: DB) -> dict[str, Any]:
    return _detail(s, _save(s, svc.get_invoice(s, invoice_id), body))


@api.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: str, s: DB) -> Response:
    svc.delete_draft(s, svc.get_invoice(s, invoice_id))
    return Response(status_code=204)


@api.post("/invoices/{invoice_id}/preview")
def preview(invoice_id: str, s: DB) -> Response:
    pdf = svc.preview_pdf(s, svc.get_invoice(s, invoice_id))
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="draft-preview.pdf"',
            "Cache-Control": "no-store",
        },
    )


@api.post("/invoices/{invoice_id}/issue")
def issue(
    invoice_id: str,
    request: Request,
    s: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    app = state(request)
    result = svc.issue(
        app.settings, invoice_id, idempotency_key or "", after_issue=archive.enqueue_on_issue
    )
    if app.worker is not None:
        app.worker.wake()
    s.expire_all()
    out = _detail(s, svc.get_invoice(s, invoice_id))
    out["replayed"] = result.replayed
    out["pdf_url"] = f"/api/v1/invoices/{invoice_id}/pdf"
    return out


@api.get("/invoices/{invoice_id}/pdf")
def download_pdf(invoice_id: str, request: Request, s: DB) -> FileResponse:
    inv = svc.get_invoice(s, invoice_id)
    if inv.status == "draft" or not inv.local_pdf_path:
        raise Conflict("invoice.not_issued", "Drafts have no issued PDF. Use Preview.")
    path = resolve(state(request).settings.data_dir, inv.local_pdf_path)
    if not path.is_file() or sha256_file(path) != inv.local_pdf_sha256:
        raise DomainError(
            "invoice.pdf_integrity", "The stored PDF is missing or altered. Restore it from backup."
        )
    filename = f"{inv.invoice_number}.pdf"
    return FileResponse(
        path, media_type="application/pdf", filename=filename, headers={"Cache-Control": "no-store"}
    )


@api.post("/invoices/{invoice_id}/duplicate", status_code=201)
def duplicate(invoice_id: str, s: DB) -> dict[str, Any]:
    return _detail(s, svc.duplicate(s, svc.get_invoice(s, invoice_id)))


@api.post("/invoices/{invoice_id}/void")
def void(invoice_id: str, body: S.VoidIn, s: DB) -> dict[str, Any]:
    return _detail(s, svc.void(s, svc.get_invoice(s, invoice_id), body.reason))


@api.post("/invoices/{invoice_id}/credit-notes/preview")
def credit_preview(invoice_id: str, body: S.CreditIn, s: DB) -> dict[str, str]:
    from locuvi.services import credit_notes

    return credit_notes.compute(s, svc.get_invoice(s, invoice_id), body.line_ids).as_strings()


@api.post("/invoices/{invoice_id}/credit-notes", status_code=201)
def credit_issue(
    invoice_id: str,
    body: S.CreditIn,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> dict[str, Any]:
    from locuvi.services import credit_notes

    cn = credit_notes.issue(
        state(request).settings, invoice_id, body.line_ids, body.reason, idempotency_key
    )
    return credit_notes.as_dict(cn)


@api.get("/credit-notes/{credit_id}/pdf")
def credit_pdf(credit_id: str, request: Request, s: DB) -> FileResponse:
    from locuvi.models import CreditNote

    cn = s.get(CreditNote, credit_id)
    if cn is None:
        raise NotFound("credit.not_found", "Credit note not found.")
    path = resolve(state(request).settings.data_dir, cn.local_pdf_path)
    if not path.is_file() or sha256_file(path) != cn.local_pdf_sha256:
        raise Conflict("credit.pdf_problem", "The credit note file is missing or altered.")
    return FileResponse(path, media_type="application/pdf", filename=f"{cn.number}.pdf")


@api.post("/invoices/{invoice_id}/split-by-month")
def split(invoice_id: str, s: DB) -> dict[str, Any]:
    parts = svc.split_by_month(s, svc.get_invoice(s, invoice_id))
    return {"invoices": [_summary(s, p) for p in parts]}


@api.get("/invoices/{invoice_id}/archive-status")
def get_archive_status(invoice_id: str, s: DB) -> dict[str, Any]:
    return archive.archive_status(s, svc.get_invoice(s, invoice_id))


@api.post("/invoices/{invoice_id}/archive-retry")
def archive_retry(invoice_id: str, request: Request, s: DB) -> dict[str, Any]:
    inv = svc.get_invoice(s, invoice_id)
    archive.request_upload(s, inv)
    if state(request).worker is not None:
        state(request).worker.wake()
    s.expire_all()
    return archive.archive_status(s, svc.get_invoice(s, invoice_id))


# ---------------------------------------------------------------------- storage


@api.get("/storage/webdav")
def get_webdav(request: Request, s: DB) -> dict[str, Any]:
    return archive.config_public(state(request).archive_ctx, core.get_storage_config(s))


@api.put("/storage/webdav")
def put_webdav(body: S.WebDavIn, request: Request, s: DB) -> dict[str, Any]:
    ctx = state(request).archive_ctx
    cfg = archive.save_config(
        s,
        ctx,
        enabled=body.enabled,
        target_url=body.target_url,
        username=body.username,
        base_path=body.base_path,
        auto_upload=body.auto_upload,
        password=body.password,
    )
    if state(request).worker is not None:
        state(request).worker.wake()
    return archive.config_public(ctx, cfg)


@api.post("/storage/webdav/test")
def test_webdav(body: S.WebDavTestIn, request: Request, s: DB) -> dict[str, Any]:
    return archive.test_connection(
        s,
        state(request).archive_ctx,
        target_url=body.target_url,
        username=body.username,
        base_path=body.base_path,
        password=body.password,
    )


@api.get("/storage/webdav/backlog")
def webdav_backlog(s: DB) -> dict[str, int]:
    return archive.archive_backlog(s)


@api.post("/storage/webdav/archive-all")
def webdav_archive_all(request: Request, s: DB) -> dict[str, Any]:
    queued = archive.request_upload_all(s)
    if state(request).worker is not None:
        state(request).worker.wake()
    return {"queued": queued, "backlog": archive.archive_backlog(s)}


@api.get("/system/info")
def system_info(request: Request) -> dict[str, Any]:
    st = state(request).settings
    return {
        "version": __version__,
        "auth_mode": st.auth_mode,
        "integrity": state(request).integrity,
        "webdav_private_allowlist": bool(st.webdav_allowlist.hosts or st.webdav_allowlist.networks),
        "webdav_password_from_secret_file": st.webdav_password_override is not None,
        "automatic_backups": st.backup_dir is not None,
    }


# ------------------------------------------------------------------------ today


@api.get("/overview")
def overview(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import checks

    out = reports.today_overview(s)
    # Today already lists these kinds in its own sections; the rest go under "Needs attention".
    shown = {
        "uninvoiced_month",
        "uninvoiced_current",
        "invoice_overdue",
        "invoice_due_soon",
        "invoice_awaiting",
        "pension_due",
    }
    out["findings"] = [
        f.as_dict() for f in checks.run_checks(s, state(request).settings) if f.kind not in shown
    ]
    return out


# ----------------------------------------------------------------------- checks


@api.get("/checks")
def list_checks(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.services import checks

    found = checks.run_checks(s, state(request).settings)
    return {"findings": [f.as_dict() for f in found], "counts": checks.summary_counts(found)}


@api.post("/checks/dismiss")
def dismiss_check(body: S.DismissIn, request: Request, s: DB, key: str) -> dict[str, bool]:
    from locuvi.services import checks

    if len(key) > 200:
        raise DomainError("checks.bad_key", "Unknown finding.")
    checks.dismiss(s, key, body.days)
    return {"ok": True}


@api.post("/system/backup")
def system_backup(request: Request) -> dict[str, Any]:
    from locuvi.services import backups

    return backups.backup_now(state(request).settings)


@api.post("/digest/send")
def digest_send(request: Request, s: DB) -> dict[str, Any]:
    from locuvi.assistant import providers
    from locuvi.services import digest

    factory = getattr(state(request), "ai_provider_factory", None)  # tests: fake provider
    provider = factory(s) if factory and providers.get_config(s).weekly_brief else None
    return digest.send_now(
        s,
        state(request).settings,
        state(request).secrets,
        smtp_factory=getattr(state(request), "smtp_factory", None),
        provider=provider,
    )


# ------------------------------------------------------------------------ diary


def _session_out(s: Session, w: Any) -> dict[str, Any]:
    inv = s.get(Invoice, w.invoice_id) if w.invoice_id else None
    return {
        "id": w.id,
        "practice_id": w.practice_id,
        "practice_name": w.practice.name,
        "date": w.date,
        "unit": w.unit,
        "quantity": str(w.quantity),
        "rate": str(w.rate),
        "pensionable": w.pensionable,
        "description": w.description,
        "status": w.status,
        "invoice": (
            {"id": inv.id, "status": inv.status, "invoice_number": inv.invoice_number}
            if inv and inv.status != "voided"
            else None
        ),
    }


@api.get("/sessions")
def list_sessions(s: DB, start: date, end: date) -> list[dict[str, Any]]:
    if (end - start).days > 400:
        raise DomainError("session.range_too_long", "Choose a shorter period.")
    return [_session_out(s, w) for w in diary.list_sessions(s, start, end)]


@api.post("/sessions", status_code=201)
def add_sessions(body: S.SessionsIn, s: DB) -> list[dict[str, Any]]:
    items = [
        diary.SessionInput(
            practice_id=x.practice_id,
            date=x.date,
            unit=x.unit,
            quantity=Decimal(x.quantity) if x.quantity else None,
            rate=Decimal(x.rate) if x.rate else None,
            pensionable=x.pensionable,
            description=x.description,
        )
        for x in body.sessions
    ]
    return [_session_out(s, w) for w in diary.add_sessions(s, items)]


@api.post("/sessions/series", status_code=201)
def add_series(body: S.SeriesIn, s: DB) -> dict[str, Any]:
    dates = diary.series_dates(body.start, body.until, body.weekdays, body.every_weeks)
    base = diary.SessionInput(
        practice_id=body.practice_id,
        date=body.start,
        unit=body.unit,
        quantity=Decimal(body.quantity) if body.quantity else None,
        rate=Decimal(body.rate) if body.rate else None,
    )
    out = diary.add_series(s, base, dates, dry_run=body.dry_run)
    if body.dry_run:
        return out
    return {"created": [_session_out(s, w) for w in out["created"]], "skipped": out["skipped"]}


@api.post("/sessions/delete-many")
def delete_many_sessions(body: S.IdsIn, s: DB) -> dict[str, int]:
    return {"deleted": diary.delete_many(s, body.ids)}


@api.patch("/sessions/{session_id}")
def patch_session(session_id: str, body: S.SessionPatch, s: DB) -> dict[str, Any]:
    ws = diary.get_session_or_404(s, session_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("quantity", "rate"):
        if data.get(k) is not None:
            data[k] = Decimal(data[k])
    return _session_out(s, diary.update_session(s, ws, **data))


@api.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, s: DB) -> Response:
    diary.delete_session(s, diary.get_session_or_404(s, session_id))
    return Response(status_code=204)


@api.get("/sessions/suggest-rate")
def suggest_rate(s: DB, practice_id: str, unit: str = "am") -> dict[str, Any]:
    p = s.get(Practice, practice_id)
    if p is None:
        raise NotFound("practice.not_found", "Practice not found.")
    r = diary.remembered_rate(s, p, unit)
    return {"rate": str(r) if r is not None else None, "pensionable": p.default_pensionable}


@api.get("/sessions/ready")
def sessions_ready(s: DB) -> list[dict[str, Any]]:
    return diary.ready_to_invoice(s)


@api.post("/sessions/invoice", status_code=201)
def invoice_from_sessions(body: S.InvoiceMonthIn, s: DB) -> dict[str, Any]:
    return _detail(s, diary.invoice_month(s, body.practice_id, body.month))


# --------------------------------------------------------------------- payments


@api.post("/invoices/{invoice_id}/payments", status_code=201)
def add_payment(invoice_id: str, body: S.PaymentIn, s: DB) -> dict[str, Any]:
    inv = svc.get_invoice(s, invoice_id)
    payments.record_payment(
        s,
        inv,
        amount=Decimal(body.amount) if body.amount else None,
        paid_on=body.paid_on,
        method=body.method,
        reference=body.reference,
    )
    return _detail(s, svc.get_invoice(s, invoice_id))


@api.delete("/payments/{payment_id}")
def remove_payment(payment_id: str, s: DB) -> dict[str, Any]:
    inv = payments.delete_payment(s, payment_id)
    return _detail(s, svc.get_invoice(s, inv.id))


# ------------------------------------------------------------------------ email


@api.get("/settings/email")
def get_email(s: DB) -> dict[str, Any]:
    from locuvi import mail

    return mail.config_public(mail.get_config(s))


@api.put("/settings/email")
def put_email(body: S.EmailConfigIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi import mail

    return mail.config_public(mail.save_config(s, state(request).secrets, body.model_dump()))


@api.post("/settings/email/test")
def test_email(request: Request, s: DB) -> dict[str, bool]:
    from locuvi import mail

    mail.send_test(
        s,
        state(request).settings,
        state(request).secrets,
        smtp_factory=getattr(state(request), "smtp_factory", None),
    )
    return {"ok": True}


@api.get("/invoices/{invoice_id}/email")
def email_draft(invoice_id: str, s: DB) -> dict[str, Any]:
    from locuvi import mail

    return mail.draft_for(s, svc.get_invoice(s, invoice_id))


@api.post("/invoices/{invoice_id}/email")
def email_send(invoice_id: str, body: S.EmailSendIn, request: Request, s: DB) -> dict[str, Any]:
    from locuvi import mail

    return mail.send_invoice(
        s,
        state(request).settings,
        state(request).secrets,
        svc.get_invoice(s, invoice_id),
        to=body.to,
        subject=body.subject,
        body=body.body,
        smtp_factory=getattr(state(request), "smtp_factory", None),
    )


# ---------------------------------------------------------------------- pension


@api.get("/pension")
def pension_months(s: DB) -> dict[str, Any]:
    p = core.get_profile(s)
    return {
        "months": pension.overview(s),
        "employee_rate": str(p.employee_rate) if p.employee_rate is not None else None,
    }


@api.get("/pension/{month}")
def pension_month(month: str, s: DB) -> dict[str, Any]:
    _check_month(month)
    return pension.month_figures(s, month)


@api.get("/pension/{month}/worksheet.pdf")
def pension_pdf(month: str, s: DB) -> Response:
    from locuvi.pdf.pension import render_pension_worksheet

    _check_month(month)
    fig = pension.month_figures(s, month)
    if not fig["forms_a"] and not fig["form_b"]["items"]:
        raise NotFound("pension.no_work", "No pensionable work or income for that month.")
    return Response(
        render_pension_worksheet(fig),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="nhs-pension-worksheet-{month}.pdf"'
        },
    )


@api.post("/pension/{month}/submitted")
def pension_submitted(month: str, body: S.PensionSubmitIn, s: DB) -> dict[str, Any]:
    _check_month(month)
    pension.mark_submitted(s, month, body.submitted_on)
    return {"months": pension.overview(s)}


@api.delete("/pension/{month}/submitted")
def pension_unsubmitted(month: str, s: DB) -> dict[str, Any]:
    _check_month(month)
    pension.unmark_submitted(s, month)
    return {"months": pension.overview(s)}


@api.post("/pension/{month}/form-a")
def pension_form_a(month: str, body: S.FormAIn, s: DB) -> dict[str, Any]:
    _check_month(month)
    if body.document_id and s.get(Document, body.document_id) is None:
        raise NotFound("document.not_found", "Document not found.")
    pension.set_form_a(s, month, body.practice_key, body.status, body.on, body.document_id)
    return pension.month_figures(s, month)


@api.put("/pension/{month}/pcse")
def pension_pcse(month: str, body: S.PcseIn, s: DB) -> dict[str, Any]:
    _check_month(month)
    pension.set_pcse(
        s,
        month,
        Decimal(body.pensionable_pay) if body.pensionable_pay else None,
        Decimal(body.contributions) if body.contributions else None,
    )
    return pension.month_figures(s, month)


@api.post("/pension/pcse/import")
def pension_pcse_import(s: DB, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    out = pension.import_pcse(s, file.file.read(2 * 1024 * 1024 + 1))
    return {**out, "months": pension.overview(s), "imported": out["months"]}


def _check_month(month: str) -> None:
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise DomainError("pension.bad_month", "Month must be YYYY-MM.")


# ---------------------------------------------------------------------- reports


@api.get("/reports/summary")
def report_summary(s: DB, tax_year: int | None = None, basis: str | None = None) -> dict[str, Any]:
    if basis not in (None, "cash", "accruals"):
        raise DomainError("reports.bad_basis", "Basis must be cash or accruals.")
    year = tax_year or reports.tax_year_of(core.today_london())
    return reports.summary(s, year, basis)


@api.get("/reports/receipts.csv")
def report_receipts_csv(s: DB, tax_year: int) -> Response:
    start, end = reports.tax_year_bounds(tax_year)
    return Response(
        reports.receipts_csv(s, start, end),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="locuvi-receipts-{tax_year}.csv"'},
    )


@api.get("/reports/invoices.csv")
def report_csv(s: DB, tax_year: int) -> Response:
    start, end = reports.tax_year_bounds(tax_year)
    return Response(
        reports.invoices_csv(s, start, end),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="locuvi-invoices-{tax_year}-{tax_year + 1}.csv"'
            )
        },
    )


@api.get("/reports/year-pack.zip")
def report_pack(s: DB, request: Request, tax_year: int) -> Response:
    data = reports.year_pack(s, state(request).settings, tax_year)
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="locuvi-{tax_year}-{tax_year + 1}.zip"'
        },
    )
