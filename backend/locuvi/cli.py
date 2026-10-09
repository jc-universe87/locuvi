"""Operator commands.

  python -m locuvi.cli backup  /backups/locuvi-YYYYmmdd.tar.gz
  python -m locuvi.cli restore /backups/locuvi-YYYYmmdd.tar.gz [--force]
  python -m locuvi.cli verify
  python -m locuvi.cli example-pdf out.pdf

Backups contain banking details: encrypt them before they leave the machine
(see README "Backups"). Uses DATA_DIR from the environment.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from locuvi.config import Settings

MANIFEST = "locuvi-backup.json"


def backup(settings: Settings, dest: Path) -> dict:
    """Consistent snapshot: SQLite online backup API + issued PDFs, as one tar.gz."""
    if not settings.db_path.exists():
        raise SystemExit(f"no database at {settings.db_path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "locuvi.db"
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        rows = dst.execute(
            "SELECT local_pdf_path, local_pdf_sha256 FROM invoice WHERE status != 'draft'"
        ).fetchall()
        n_invoices = len(rows)
        try:  # credit notes (migration 0012+) are immutable PDFs too
            rows += dst.execute(
                "SELECT local_pdf_path, local_pdf_sha256 FROM credit_note"
            ).fetchall()
        except sqlite3.OperationalError:
            pass
        src.close()
        dst.close()
        from locuvi.storage.local import sha256_file

        # Never write a backup that restore() would later reject: every issued PDF must
        # exist and match its recorded checksum.
        bad = [
            rel
            for rel, sha in rows
            if not (settings.data_dir / rel).is_file()
            or sha256_file(settings.data_dir / rel) != sha
        ]
        if bad:
            raise SystemExit(
                f"backup aborted: {len(bad)} issued PDF(s) missing or altered "
                f"(e.g. {bad[0]}); run `locuvi verify` and restore them first"
            )
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "issued_invoices": n_invoices,
            "credit_notes": len(rows) - n_invoices,
            "pdfs": {p: sha for p, sha in rows},
        }
        (Path(tmp) / MANIFEST).write_text(json.dumps(manifest, indent=2))
        partial = dest.with_name(dest.name + ".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(snap, arcname="locuvi.db")
            tar.add(Path(tmp) / MANIFEST, arcname=MANIFEST)
            for rel, _ in rows:
                tar.add(settings.data_dir / rel, arcname=rel)
        partial.chmod(0o600)
        partial.replace(dest)
    from locuvi.services.checks import record_backup

    record_backup(settings)
    return manifest


def restore(settings: Settings, src: Path, force: bool = False) -> dict:
    from locuvi.storage.local import sha256_file

    if settings.db_path.exists() and not force:
        raise SystemExit("DATA_DIR already has a database; stop the app and use --force")
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(src, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        root = Path(tmp)
        manifest = json.loads((root / MANIFEST).read_text())
        for rel, sha in manifest["pdfs"].items():
            f = root / rel
            if not f.is_file() or sha256_file(f) != sha:
                raise SystemExit(f"backup is damaged: {rel} missing or altered")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
        shutil.copy2(root / "locuvi.db", settings.db_path)
        for rel in manifest["pdfs"]:
            target = settings.data_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, target)
    return manifest


def verify(settings: Settings) -> dict:
    from locuvi import db, integrity

    db.init_engine(settings.db_path)
    with db.new_session() as s:
        return integrity.check(s, settings, quarantine=False)


def example_snapshot() -> dict:
    """Entirely fictional data for documentation."""
    from locuvi.money import LineInput, PensionPolicyValues, calculate_totals

    lines = [
        ("2026-10-08", "GP locum AM session", "am", "1", "600.00", True),
        ("2026-10-15", "GP locum PM session", "pm", "1", "550.00", True),
        ("2026-10-22", "GP locum hours (extended access)", "hours", "3.5", "95.00", True),
        ("2026-10-22", "Mileage (non-pensionable expense)", "custom", "1", "18.40", False),
    ]
    from datetime import date
    from decimal import Decimal

    policy = PensionPolicyValues(date(2026, 4, 1), Decimal("0.90"), Decimal("0.1438"))
    totals = calculate_totals(
        [
            LineInput(date.fromisoformat(d), Decimal(q), Decimal(p), pen)
            for d, _, _, q, p, pen in lines
        ],
        pension_enabled=True,
        policy=policy,
    )
    return {
        "schema_version": 1,
        "invoice": {
            "id": "00000000-0000-4000-8000-000000000000",
            "number": "LOC-2026-0001",
            "invoice_date": "2026-10-23",
            "due_date": "2026-11-22",
            "work_start_date": "2026-10-08",
            "work_end_date": "2026-10-22",
            "reference": "PO-EXAMPLE-17",
            "notes": "Thank you. Please quote the invoice number with your payment.",
            "currency": "GBP",
            "issued_at": "2026-10-23T09:00:00+00:00",
        },
        "seller": {
            "legal_name": "Dr Alex Example",
            "trading_name": None,
            "designation": "General Practitioner (Locum) · FICTIONAL EXAMPLE",
            "address_lines": ["1 Sample Street", "Exampletown"],
            "postcode": "EX1 1AA",
            "email": "alex@example.invalid",
            "phone": None,
        },
        "bill_to": {
            "practice_id": None,
            "name": "Example Medical Practice",
            "address_lines": ["2 Test Road", "Sampleford", "SF1 2BB"],
            "contact_name": "Practice Manager",
            "billing_email": "accounts@example.invalid",
            "reference": None,
        },
        "bank": {
            "account_holder": "Dr Alex Example",
            "sort_code": "00-00-00",
            "account_number": "00000000",
        },
        "lines": [
            {
                "service_date": d,
                "description": desc,
                "unit": u,
                "quantity": q,
                "unit_price": p,
                "amount": str(a),
                "pensionable": pen,
            }
            for (d, desc, u, q, p, pen), a in zip(lines, totals.line_amounts, strict=True)
        ],
        "totals": totals.as_strings(),
        "pension": {
            "enabled": True,
            "policy_id": None,
            "policy_label": None,
            "effective_from": "2026-04-01",
            "pensionable_fraction": "0.90",
            "employer_rate": "0.1438",
            "rounding": "ROUND_HALF_UP",
        },
        "vat": {"status": "not_vat_registered", "amount": None},
        "presentation": {"locale": "en-GB", "timezone": "Europe/London", "template": "a4-v1"},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="locuvi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("dest", type=Path)
    r = sub.add_parser("restore")
    r.add_argument("src", type=Path)
    r.add_argument("--force", action="store_true")
    sub.add_parser("verify")
    e = sub.add_parser("example-pdf")
    e.add_argument("out", type=Path)
    args = ap.parse_args(argv)
    settings = Settings.from_env()

    if args.cmd == "backup":
        m = backup(settings, args.dest)
        print(f"backup written: {args.dest} ({m['issued_invoices']} issued PDFs)")
    elif args.cmd == "restore":
        m = restore(settings, args.src, args.force)
        print(f"restored {m['issued_invoices']} issued PDFs and database from {args.src}")
        print("start the app and check /api/v1/health/ready")
    elif args.cmd == "verify":
        result = verify(settings)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    elif args.cmd == "example-pdf":
        from locuvi.pdf.render import render_invoice_pdf

        args.out.write_bytes(render_invoice_pdf(example_snapshot()))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
