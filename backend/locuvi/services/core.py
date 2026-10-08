"""Singletons, policy lookup and small shared helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.models import (
    AuditEvent,
    InvoiceSequence,
    OwnerProfile,
    PensionPolicy,
    StorageConfig,
)
from locuvi.money import PensionPolicyValues

LONDON = ZoneInfo("Europe/London")


def today_london(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(LONDON).date()


def get_profile(s: Session) -> OwnerProfile:
    profile = s.get(OwnerProfile, 1)
    if profile is None:
        profile = OwnerProfile(id=1)
        s.add(profile)
        s.flush()
    return profile


def get_sequence(s: Session) -> InvoiceSequence:
    seq = s.get(InvoiceSequence, 1)
    if seq is None:
        seq = InvoiceSequence(id=1, prefix=f"LOC-{today_london().year}-", next_number=1)
        s.add(seq)
        s.flush()
    return seq


def get_storage_config(s: Session) -> StorageConfig:
    cfg = s.get(StorageConfig, 1)
    if cfg is None:
        cfg = StorageConfig(id=1)
        s.add(cfg)
        s.flush()
    return cfg


def ensure_singletons(s: Session) -> None:
    get_profile(s)
    get_sequence(s)
    get_storage_config(s)
    s.commit()


def format_number(prefix: str, n: int, padding: int) -> str:
    return f"{prefix}{n:0{padding}d}"


def policy_values(p: PensionPolicy) -> PensionPolicyValues:
    return PensionPolicyValues(
        effective_from=p.effective_from,
        pensionable_fraction=p.pensionable_fraction,
        employer_rate=p.employer_rate,
        label=p.label,
    )


def all_policies(s: Session) -> list[PensionPolicy]:
    return list(s.scalars(select(PensionPolicy).order_by(PensionPolicy.effective_from)))


def policy_for_date(s: Session, on: date) -> PensionPolicy | None:
    return s.scalars(
        select(PensionPolicy)
        .where(PensionPolicy.effective_from <= on)
        .order_by(PensionPolicy.effective_from.desc())
        .limit(1)
    ).first()


def audit(s: Session, event_type: str, **metadata: Any) -> None:
    s.add(AuditEvent(event_type=event_type, metadata_json=metadata))
