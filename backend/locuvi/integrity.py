"""Startup consistency check between issued invoice rows and PDF files."""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.config import Settings
from locuvi.models import Invoice
from locuvi.storage.local import sha256_file

log = logging.getLogger("locuvi.integrity")


def check(s: Session, settings: Settings, *, quarantine: bool = True) -> dict[str, Any]:
    """Verify issued rows against files.

    ``quarantine`` must only be True at startup (no issue can be in flight);
    the read-only ``verify`` command passes False.
    """
    problems: list[dict[str, str]] = []
    referenced: set[str] = set()
    rows = s.scalars(select(Invoice).where(Invoice.status != "draft")).all()
    for inv in rows:
        if not inv.local_pdf_path or not inv.local_pdf_sha256 or not inv.invoice_number:
            problems.append({"invoice_id": inv.id, "problem": "incomplete_issue_record"})
            continue
        referenced.add(inv.local_pdf_path)
        path = settings.data_dir / inv.local_pdf_path
        if not path.is_file():
            problems.append({"invoice_id": inv.id, "problem": "pdf_missing"})
        elif sha256_file(path) != inv.local_pdf_sha256:
            problems.append({"invoice_id": inv.id, "problem": "pdf_checksum_mismatch"})

    from locuvi.models import CreditNote

    credits = s.scalars(select(CreditNote)).all()
    for cn in credits:
        referenced.add(cn.local_pdf_path)
        path = settings.data_dir / cn.local_pdf_path
        if not path.is_file():
            problems.append({"invoice_id": cn.invoice_id, "problem": "credit_pdf_missing"})
        elif sha256_file(path) != cn.local_pdf_sha256:
            problems.append(
                {"invoice_id": cn.invoice_id, "problem": "credit_pdf_checksum_mismatch"}
            )

    # PDFs that no issued row references come from an issue that never committed.
    quarantined = 0
    for folder in ("issued", "credit"):
        d = settings.data_dir / "invoices" / folder
        if not (quarantine and d.is_dir()):
            continue
        for f in d.iterdir():
            rel = f"invoices/{folder}/{f.name}"
            if f.name.startswith(".") and f.name.endswith(".tmp"):
                f.unlink(missing_ok=True)
                continue
            if f.suffix == ".pdf" and rel not in referenced:
                settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
                os.replace(f, settings.quarantine_dir / f.name)
                quarantined += 1
    for p in problems:
        log.error("integrity problem invoice=%s %s", p["invoice_id"], p["problem"])
    if quarantined:
        log.warning("moved %d unreferenced PDF(s) to quarantine", quarantined)
    return {
        "ok": not problems,
        "issued_checked": len(rows),
        "problems": problems,
        "quarantined": quarantined,
    }
