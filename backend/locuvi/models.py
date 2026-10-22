"""ORM entities (engineering/DATA_MODEL.md).

Monetary amounts and quantities are stored as exact decimal TEXT, never REAL.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class DecimalString(TypeDecorator[Decimal]):
    """Stores Decimal as canonical TEXT so SQLite never coerces it to float."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("float is not allowed for decimal columns")
        return str(Decimal(value))

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        return None if value is None else Decimal(value)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes (SQLite drops tzinfo otherwise)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class VatStatus(enum.StrEnum):
    not_vat_registered = "not_vat_registered"
    vat_registered = "vat_registered"


class InvoiceStatus(enum.StrEnum):
    draft = "draft"
    issued = "issued"
    voided = "voided"


class LineUnit(enum.StrEnum):
    am = "am"
    pm = "pm"
    day = "day"
    hours = "hours"
    custom = "custom"


class ArchiveStatus(enum.StrEnum):
    not_configured = "not_configured"
    pending = "pending"
    uploading = "uploading"
    synced = "synced"
    failed = "failed"
    conflict = "conflict"


class OwnerProfile(TimestampMixin, Base):
    """Singleton (id is always 1)."""

    __tablename__ = "owner_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    trading_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    designation: Mapped[str] = mapped_column(String(200), default="")
    address_lines: Mapped[str] = mapped_column(Text, default="")
    postcode: Mapped[str] = mapped_column(String(20), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_account_holder: Mapped[str] = mapped_column(String(200), default="")
    bank_sort_code: Mapped[str] = mapped_column(String(8), default="")
    bank_account_number: Mapped[str] = mapped_column(String(8), default="")
    vat_status: Mapped[str] = mapped_column(String(32), default=VatStatus.not_vat_registered)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    pension_default_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Only used on pension worksheets, never on invoices.
    professional_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pension_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    employee_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Self Assessment basis: "cash" (HMRC default for sole traders) or "accruals" (invoiced)
    accounting_basis: Mapped[str] = mapped_column(String(10), default="cash")
    # Personalisation (services/branding.py); frozen into each issued snapshot.
    logo_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_svg: Mapped[str | None] = mapped_column(Text, nullable=True)  # cleaned vector logo
    brand_accent: Mapped[str] = mapped_column(String(20), default="steel")
    invoice_footer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    email_signoff: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Email reminders before NHS pension deadlines (services/pension_reminders.py): opt-in, and
    # the reminders already sent, so each one goes out once.
    pension_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    pension_reminders_sent: Mapped[list[str]] = mapped_column(JSON, default=list)


class InvoiceSequence(TimestampMixin, Base):
    """Singleton numbering row (id is always 1); locked by BEGIN IMMEDIATE on issue."""

    __tablename__ = "invoice_sequence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    prefix: Mapped[str] = mapped_column(String(40), default="LOC-2026-")
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    padding: Mapped[int] = mapped_column(Integer, default=4)
    credit_prefix: Mapped[str] = mapped_column(String(40), default="CN-")
    credit_next_number: Mapped[int] = mapped_column(Integer, default=1)


class PensionPolicy(TimestampMixin, Base):
    """Effective-dated employer contribution policy. Rows are append-only."""

    __tablename__ = "pension_policy"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    effective_from: Mapped[date] = mapped_column(Date, unique=True)
    pensionable_fraction: Mapped[Decimal] = mapped_column(DecimalString)
    employer_rate: Mapped[Decimal] = mapped_column(DecimalString)
    label: Mapped[str] = mapped_column(String(200), default="")
    source_note: Mapped[str] = mapped_column(Text, default="")


class Practice(TimestampMixin, Base):
    __tablename__ = "practice"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    billing_address: Mapped[str] = mapped_column(Text, default="")
    billing_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    default_unit: Mapped[str] = mapped_column(String(16), default=LineUnit.am)
    default_pensionable: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_includes_pension: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hourly practices: default_unit == "hours", paid hourly_rate × default_hours by default.
    hourly_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    default_hours: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    default_payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    practice_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Practice-specific invoicing instructions (structured, so rules and the assistant can use them)
    po_required: Mapped[bool] = mapped_column(Boolean, default=False)
    invoice_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_a_signatory: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoice"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(16), default=InvoiceStatus.draft, index=True)
    invoice_number: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    practice_id: Mapped[str | None] = mapped_column(
        ForeignKey("practice.id"), nullable=True, index=True
    )
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    pension_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Totals are frozen on issue; on drafts they are a convenience cache.
    fee_subtotal: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    pensionable_basic_total: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    pensionable_pay: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    employer_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    employer_contribution: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    vat_amount: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    grand_total: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    pension_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("pension_policy.id"), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    immutable_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    local_pdf_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    local_pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_pdf_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_idempotency_key: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True
    )
    duplicated_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_emailed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    practice: Mapped[Practice | None] = relationship(lazy="joined")
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLine.sort_order",
        lazy="selectin",
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="invoice", order_by="Payment.paid_on", lazy="selectin"
    )
    credit_notes: Mapped[list[CreditNote]] = relationship(
        "CreditNote", order_by="CreditNote.created_at", viewonly=True
    )
    # The invoice's own archive copies (credit-note copies have credit_note_id set).
    archive_jobs: Mapped[list[ArchiveJob]] = relationship(
        back_populates="invoice",
        order_by="ArchiveJob.created_at",
        lazy="selectin",
        primaryjoin=(
            "and_(Invoice.id == ArchiveJob.invoice_id, ArchiveJob.credit_note_id.is_(None))"
        ),
    )


class InvoiceLine(TimestampMixin, Base):
    __tablename__ = "invoice_line"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"), index=True
    )
    service_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(16), default=LineUnit.am)
    quantity: Mapped[Decimal] = mapped_column(DecimalString)
    unit_price: Mapped[Decimal] = mapped_column(DecimalString)
    amount: Mapped[Decimal] = mapped_column(DecimalString)
    pensionable: Mapped[bool] = mapped_column(Boolean, default=False)
    # Rate agreed *including* the employer pension contribution; unit_price is then derived
    # from it (money.basic_from_inclusive) whenever pension applies to the line.
    agreed_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class InvoiceEvent(Base):
    __tablename__ = "invoice_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(60))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class StorageConfig(Base):
    """Singleton WebDAV configuration (id is always 1)."""

    __tablename__ = "storage_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    target_url: Mapped[str] = mapped_column(String(500), default="")
    username: Mapped[str] = mapped_column(String(200), default="")
    base_path: Mapped[str] = mapped_column(String(300), default="Locuvi/Invoices")
    auto_upload: Mapped[bool] = mapped_column(Boolean, default=True)
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ArchiveJob(TimestampMixin, Base):
    __tablename__ = "archive_job"
    __table_args__ = (UniqueConstraint("invoice_id", "destination_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice.id"), index=True)
    # Base URL + username + remote path; never recomputed after creation.
    destination_key: Mapped[str] = mapped_column(String(800))
    destination_url_snapshot: Mapped[str] = mapped_column(String(500))
    destination_path_snapshot: Mapped[str] = mapped_column(String(500))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=ArchiveStatus.pending, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error_class: Mapped[str | None] = mapped_column(String(60), nullable=True)
    remote_etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when this job archives a credit note (of invoice_id) rather than the invoice itself.
    credit_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("credit_note.id"), nullable=True, index=True
    )

    invoice: Mapped[Invoice] = relationship(back_populates="archive_jobs")


class AuditEvent(Base):
    """System-level audit (settings changes, archive config), without secrets."""

    __tablename__ = "audit_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(60))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SessionStatus(enum.StrEnum):
    active = "active"
    cancelled = "cancelled"


class WorkSession(TimestampMixin, Base):
    """A booked or worked locum session (diary). Past active sessions count as worked."""

    __tablename__ = "work_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    practice_id: Mapped[str] = mapped_column(ForeignKey("practice.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    unit: Mapped[str] = mapped_column(String(16), default=LineUnit.am)
    quantity: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal("1"))
    rate: Mapped[Decimal] = mapped_column(DecimalString)
    pensionable: Mapped[bool] = mapped_column(Boolean, default=True)
    # The rate above was agreed including the employer pension contribution.
    rate_includes_pension: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default=SessionStatus.active)
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice.id"), nullable=True, index=True
    )

    practice: Mapped[Practice] = relationship(lazy="joined")


class Payment(Base):
    """Money received against an invoice. Separate rows; the invoice never changes."""

    __tablename__ = "payment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice.id"), index=True)
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(DecimalString)
    method: Mapped[str] = mapped_column(String(30), default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class EmailConfig(Base):
    """Singleton SMTP configuration (id is always 1). Password encrypted like WebDAV."""

    __tablename__ = "email_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    host: Mapped[str] = mapped_column(String(200), default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    security: Mapped[str] = mapped_column(String(10), default="starttls")
    username: Mapped[str] = mapped_column(String(200), default="")
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address: Mapped[str] = mapped_column(String(200), default="")
    from_name: Mapped[str] = mapped_column(String(200), default="")
    bcc_self: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PensionSubmission(Base):
    """Owner's record that a month's Locum A/B figures were submitted (frozen figures)."""

    __tablename__ = "pension_submission"
    __table_args__ = (UniqueConstraint("month"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    submitted_on: Mapped[date] = mapped_column(Date)
    figures_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FindingDismissal(Base):
    """Owner chose to hide a finding until a date (findings reappear if still true)."""

    __tablename__ = "finding_dismissal"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    until: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Document(TimestampMixin, Base):
    """Inbox item: an uploaded file or pasted text (booking email, remittance, form...).

    Files live under ``data_dir/documents``; ``text_content`` holds extracted or pasted text.
    """

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    title: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(10), default="upload")  # upload | paste
    filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stored_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text_content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)  # new | done
    practice_id: Mapped[str | None] = mapped_column(
        ForeignKey("practice.id"), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    mail_folder: Mapped[str | None] = mapped_column(String(300), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice.id"), nullable=True, index=True
    )


class MailboxConfig(Base):
    """One email account the owner connected (several allowed): read-only access to the
    folders they chose, by IMAP (password encrypted) or Microsoft sign-in (Graph, Mail.Read
    only; refresh token encrypted). The account type is fixed when it is added."""

    __tablename__ = "mailbox_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(100), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(12), default="imap")  # imap | microsoft
    ms_client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ms_tenant: Mapped[str] = mapped_column(String(64), default="common")
    ms_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder_labels: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    host: Mapped[str] = mapped_column(String(200), default="")
    port: Mapped[int] = mapped_column(Integer, default=993)
    security: Mapped[str] = mapped_column(String(10), default="ssl")  # ssl | starttls
    username: Mapped[str] = mapped_column(String(200), default="")
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    folders: Mapped[list[str]] = mapped_column(JSON, default=list)
    since_days: Mapped[int] = mapped_column(Integer, default=90)
    auto_scan: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class MailFolderState(Base):
    """How far each chosen folder of an account has been read (IMAP UIDVALIDITY + last UID
    seen, or the Microsoft delta link)."""

    __tablename__ = "mail_folder_progress"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("mailbox_config.id", ondelete="CASCADE"), primary_key=True
    )
    folder: Mapped[str] = mapped_column(String(300), primary_key=True)
    uidvalidity: Mapped[int] = mapped_column(Integer, default=0)
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)  # Microsoft delta link


class AssistantConfig(Base):
    """Singleton (id 1): optional AI assistant. Off by default; API key encrypted."""

    __tablename__ = "assistant_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(20), default="anthropic")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)  # None = default
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)  # own server only
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekly_brief: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Proposal(Base):
    """Audit record of a suggestion (rules or AI) and what the owner decided.

    ``payload_json`` is exactly what was proposed (after server validation);
    ``result_json`` records what was created or changed on acceptance.
    """

    __tablename__ = "proposal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30), default="sessions")
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("document.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    engine: Mapped[str] = mapped_column(String(60), default="rules")  # rules | ai:<model>
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BankTransaction(Base):
    """A credit (money in) from an imported bank statement. Debits are never stored.

    status: suggested (a deterministic match is proposed) | unmatched | matched | ignored.
    """

    __tablename__ = "bank_transaction"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    booked_on: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(DecimalString)
    description: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(12), default="unmatched", index=True)
    suggestion_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class FormARecord(Base):
    """Owner's progress on one practice's GP Locum Form A for a month (sent → signed)."""

    __tablename__ = "form_a_record"
    __table_args__ = (UniqueConstraint("month", "practice_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    month: Mapped[str] = mapped_column(String(7), index=True)
    practice_key: Mapped[str] = mapped_column(String(200))  # practice id, or billed name
    status: Mapped[str] = mapped_column(String(10), default="sent")  # sent | signed
    sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    signed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("document.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PcseRecord(Base):
    """What PCSE / NHS Pensions shows as recorded for a month (imported or typed in)."""

    __tablename__ = "pcse_record"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    pensionable_pay: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    contributions: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | csv
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AgentConversation(Base):
    """A conversation with the administrative agent: messages for follow-ups + tool-call log."""

    __tablename__ = "agent_conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200), default="")
    messages_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    steps_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AgentToken(Base):
    """Access token for an external agent platform (Bevro) using Locuvi's MCP endpoint.

    Only a SHA-256 of the token is stored; the token is shown once when created.
    """

    __tablename__ = "agent_token"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), default="Bevro")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(12), default="")  # last characters, for recognition
    allow_drafts: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CalendarFeed(Base):
    """Singleton (id 1): private ICS subscription link for booked sessions.

    The secret is kept encrypted (so the link can be shown again) plus a hash for lookup.
    """

    __tablename__ = "calendar_feed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    include_fees: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CreditNote(Base):
    """Credit against an issued invoice (whole lines). Immutable once created, like invoices:
    own number series, frozen snapshot and PDF. Amounts are positive and reduce what is owed."""

    __tablename__ = "credit_note"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(60), unique=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice.id"), index=True)
    credit_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    line_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    fee_subtotal: Mapped[Decimal] = mapped_column(DecimalString)
    pensionable_basic_total: Mapped[Decimal] = mapped_column(DecimalString)
    pensionable_pay: Mapped[Decimal] = mapped_column(DecimalString)
    employer_contribution: Mapped[Decimal] = mapped_column(DecimalString)
    grand_total: Mapped[Decimal] = mapped_column(DecimalString)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    local_pdf_path: Mapped[str] = mapped_column(String(300))
    local_pdf_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuthConfig(Base):
    """Singleton (id 1): owner password set in the app (scrypt hash; overrides the secret file)
    and the session epoch — bumping it signs out every existing session."""

    __tablename__ = "auth_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TrashItem(Base):
    """Recently deleted: a JSON snapshot of deleted rows, restorable for 30 days.

    ``payload_json`` holds the rows (decimals as strings, dates ISO); ``summary_json`` is
    what the bin shows (the frontend words it). Purged automatically after 30 days.
    """

    __tablename__ = "trash_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(300), default="")
    deleted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
