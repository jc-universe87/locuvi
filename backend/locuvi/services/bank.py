"""Bank statement CSV import and deterministic payment matching (roadmap step 4, spec D).

Privacy: only credits (money in) are kept; debits, balances and account numbers in the file are
ignored and never stored, and the file itself is not kept.

Matching is rule-based and explainable, strongest first:
  number    the invoice number appears in the description and the amount fits what is owed
  combined  the amount equals the outstanding total of 2–4 invoices of one practice
  amount    the amount equals what one invoice still owes (stronger if the practice is named)
Every match is a *suggestion*; payments are recorded only when the owner confirms.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi.errors import Conflict, DomainError, NotFound
from locuvi.models import BankTransaction, Invoice, InvoiceStatus, Payment, utcnow
from locuvi.money import ZERO, round_money
from locuvi.services import core, payments

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000

_DATE_COLS = ("transaction date", "date", "posted date", "posting date", "booking date",
              "value date", "completed date", "started date")  # fmt: skip
_AMOUNT_COLS = ("amount", "amount (gbp)", "value", "amount gbp", "transaction amount")
_CREDIT_COLS = ("credit amount", "paid in", "money in", "credit", "credits", "in")
_DESC_COLS = ("description", "transaction description", "details", "narrative", "memo",
              "reference", "name", "counter party", "payee", "merchant", "notes and #tags",
              "transaction details", "type")  # fmt: skip


# ------------------------------------------------------------------- parsing


def parse_amount(raw: str) -> Decimal | None:
    s = (raw or "").strip().replace("£", "").replace("GBP", "").replace(",", "").strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    upper = s.upper()
    if upper.endswith("CR"):
        s = s[:-2].strip()
    elif upper.endswith("DR"):
        neg, s = True, s[:-2].strip()
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return -d if neg else d


def parse_date(raw: str) -> date | None:
    s = (raw or "").strip()[:30]
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y",
                "%d-%b-%Y", "%d %B %Y", "%d-%b-%y", "%Y/%m/%d"):  # fmt: skip
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _find(headers: list[str], names: tuple[str, ...]) -> int | None:
    norm = [h.strip().lower() for h in headers]
    for n in names:
        if n in norm:
            return norm.index(n)
    return None


def parse_statement(data: bytes) -> list[dict[str, Any]]:
    """Credits as {booked_on, amount, description}. Raises DomainError if unreadable."""
    if len(data) > MAX_BYTES:
        raise DomainError("bank.too_large", "Statements up to 5 MB can be imported.")
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text or not text.strip():
        raise DomainError("bank.empty", "That file is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise DomainError("bank.empty", "That file is empty.")
    # header row: the first row (within the first 10) naming a date column
    header_idx = next(
        (i for i, r in enumerate(rows[:10]) if _find(r, _DATE_COLS) is not None), None
    )
    out: list[dict[str, Any]] = []
    if header_idx is not None:
        h = rows[header_idx]
        di, ai = _find(h, _DATE_COLS), _find(h, _AMOUNT_COLS)
        ci = _find(h, _CREDIT_COLS)
        desc_cols = [i for i, name in enumerate(h) if name.strip().lower() in _DESC_COLS]
        if ai is None and ci is None:
            raise DomainError("bank.no_amount", "Couldn't find an amount column in this file.")
        body = rows[header_idx + 1 :]
    else:  # headerless (e.g. HSBC): date, description, amount
        di, ai, ci, desc_cols = 0, 2, None, [1]
        body = rows
    for r in body[:MAX_ROWS]:
        try:
            d = parse_date(r[di])  # type: ignore[index]
        except IndexError:
            continue
        if d is None:
            continue
        amount = None
        if ci is not None and ci < len(r):
            amount = parse_amount(r[ci])
        if amount is None and ai is not None and ai < len(r):
            amount = parse_amount(r[ai])
        if amount is None or amount <= 0:
            continue  # debits and blanks are ignored entirely
        if amount.as_tuple().exponent < -2:  # type: ignore[operator]
            continue
        desc = " ".join(r[i].strip() for i in desc_cols if i < len(r) and r[i].strip())
        out.append({"booked_on": d, "amount": round_money(amount),
                    "description": re.sub(r"\s+", " ", desc)[:300]})  # fmt: skip
    if header_idx is None and not out:
        raise DomainError("bank.unreadable", "Couldn't read this statement. Export it as CSV.")
    return out


# ------------------------------------------------------------------- matching


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _open_invoices(s: Session) -> list[tuple[Invoice, Decimal]]:
    out = []
    for inv in s.scalars(select(Invoice).where(Invoice.status == InvoiceStatus.issued)):
        owed = payments.outstanding(inv)
        if owed > 0:
            out.append((inv, owed))
    return out


def _practice_name(inv: Invoice) -> str:
    return (inv.immutable_snapshot_json or {}).get("bill_to", {}).get("name", "") or (
        inv.practice.name if inv.practice else ""
    )


def _named(desc: str, inv: Invoice) -> bool:
    """Practice name (or a distinctive word of it) appears in the description."""
    nd = _norm(desc)
    name = _practice_name(inv)
    if len(_norm(name)) >= 4 and _norm(name) in nd:
        return True
    words = [w for w in re.findall(r"[a-z]{5,}", name.lower())
             if w not in {"medical", "practice", "surgery", "health", "centre", "center", "group",
                          "partnership"}]  # fmt: skip
    return any(w in desc.lower() for w in words)


def suggest(s: Session, booked_on: date, amount: Decimal, desc: str,
            reserved: set[str] | None = None) -> dict[str, Any] | None:  # fmt: skip
    reserved = reserved or set()
    open_inv = [(i, o) for i, o in _open_invoices(s) if i.id not in reserved]
    nd = _norm(desc)

    def pack(kind: str, conf: str, items: list[tuple[Invoice, Decimal]]) -> dict[str, Any]:
        return {"kind": kind, "confidence": conf, "invoices": [
            {"id": i.id, "number": i.invoice_number, "practice": _practice_name(i),
             "amount": str(a)} for i, a in items]}  # fmt: skip

    # 1. invoice number in the reference
    by_number = [(i, o) for i, o in open_inv if i.invoice_number and _norm(i.invoice_number) in nd]
    if len(by_number) == 1:
        inv, owed = by_number[0]
        if amount <= owed:
            return pack("number", "high", [(inv, amount)])
    elif len(by_number) > 1:
        total = sum((o for _, o in by_number), ZERO)
        if total == amount:
            return pack("number", "high", by_number)
    # 2. exact outstanding of one invoice
    exact = [(i, o) for i, o in open_inv if o == amount and i.issued_at is not None
             and (i.invoice_date or booked_on) <= booked_on]  # fmt: skip
    named = [(i, o) for i, o in exact if _named(desc, i)]
    if len(named) == 1:
        return pack("amount_practice", "high", named)
    if len(exact) == 1:
        return pack("amount", "medium", exact)
    # 3. combined payment for one practice (2-4 invoices)
    by_practice: dict[str, list[tuple[Invoice, Decimal]]] = {}
    for i, o in open_inv:
        if (i.invoice_date or booked_on) <= booked_on:
            by_practice.setdefault(i.practice_id or _practice_name(i), []).append((i, o))
    found = []
    for items in by_practice.values():
        items = sorted(items, key=lambda x: x[0].invoice_date or booked_on)[:12]
        for n in (2, 3, 4):
            for combo in combinations(items, n):
                if sum((o for _, o in combo), ZERO) == amount:
                    found.append(list(combo))
    if len(found) == 1:
        conf = "high" if _named(desc, found[0][0][0]) else "medium"
        return pack("combined", conf, found[0])
    return None


# ------------------------------------------------------------------- import


def _fingerprint(row: dict[str, Any], occurrence: int) -> str:
    key = f"{row['booked_on']}|{row['amount']}|{row['description']}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()


def import_statement(s: Session, filename: str, data: bytes) -> dict[str, Any]:
    rows = parse_statement(data)
    seen: dict[tuple[Any, ...], int] = {}
    new = 0
    dup = 0
    for row in rows:
        k = (row["booked_on"], row["amount"], row["description"])
        seen[k] = seen.get(k, 0) + 1
        fp = _fingerprint(row, seen[k])
        if s.scalars(select(BankTransaction.id).where(BankTransaction.fingerprint == fp)).first():
            dup += 1
            continue
        s.add(BankTransaction(fingerprint=fp, booked_on=row["booked_on"], amount=row["amount"],
                              description=row["description"],
                              source_name=(filename or "statement.csv")[:200]))  # fmt: skip
        new += 1
    s.flush()
    rematch(s)
    core.audit(s, "bank.imported", credits=len(rows), new=new, duplicates=dup)
    s.commit()
    counts = summary(s)
    return {"credits": len(rows), "new": new, "duplicates": dup, **counts}


def rematch(s: Session) -> None:
    """Refresh suggestions for every undecided credit (oldest first, no double use)."""
    reserved: set[str] = set()
    pending = s.scalars(
        select(BankTransaction)
        .where(BankTransaction.status.in_(["unmatched", "suggested"]))
        .order_by(BankTransaction.booked_on)
    )
    for tx in pending:
        sug = suggest(s, tx.booked_on, tx.amount, tx.description, reserved)
        tx.suggestion_json = sug
        tx.status = "suggested" if sug else "unmatched"
        if sug:
            reserved.update(i["id"] for i in sug["invoices"])


def summary(s: Session) -> dict[str, int]:
    out = {"suggested": 0, "unmatched": 0, "matched": 0, "ignored": 0}
    for st in s.scalars(select(BankTransaction.status)):
        out[st] = out.get(st, 0) + 1
    return out


def get(s: Session, tx_id: str) -> BankTransaction:
    tx = s.get(BankTransaction, tx_id)
    if tx is None:
        raise NotFound("bank.not_found", "Transaction not found.")
    return tx


def accept(s: Session, tx: BankTransaction, invoice_ids: list[str] | None = None) -> None:
    """Record payment(s) for a credit: the suggestion, or invoices the owner picked."""
    if tx.status not in {"suggested", "unmatched"}:
        raise Conflict("bank.decided", "This payment has already been handled.")
    if invoice_ids is None:
        if not tx.suggestion_json:
            raise DomainError("bank.choose_invoice", "Choose the invoice this payment is for.")
        plan = [(i["id"], Decimal(i["amount"])) for i in tx.suggestion_json["invoices"]]
    else:
        plan, left = [], tx.amount
        for iid in invoice_ids[:10]:
            inv = s.get(Invoice, iid)
            if inv is None or inv.status != InvoiceStatus.issued:
                raise NotFound("invoice.not_found", "Invoice not found.")
            owed = payments.outstanding(inv)
            part = min(owed, left)
            if part <= 0:
                break
            plan.append((iid, part))
            left -= part
        if not plan:
            raise DomainError("bank.choose_invoice", "Choose the invoice this payment is for.")
    # One transaction: every payment and the "matched" mark commit together, or nothing does.
    try:
        created: list[str] = []
        for iid, amt in plan:
            inv = s.get(Invoice, iid)
            if inv is None:
                raise NotFound("invoice.not_found", "Invoice not found.")
            p = payments.record_payment(s, inv, amount=amt, paid_on=tx.booked_on,
                                        method="bank_transfer",
                                        reference=tx.description[:100] or None,
                                        commit=False)  # fmt: skip
            created.append(p.id)
        tx.status = "matched"
        tx.payment_ids = created
        tx.decided_at = utcnow()
        core.audit(s, "bank.matched", transaction_id=tx.id, payments=len(created),
                   kind=(tx.suggestion_json or {}).get("kind", "manual") if invoice_ids is None
                   else "manual")  # fmt: skip
        rematch(s)
        s.commit()
    except BaseException:
        s.rollback()
        raise


def accept_all(s: Session) -> int:
    """Confirm every high-confidence suggestion. Returns how many were recorded."""
    n = 0
    for tx in list(s.scalars(select(BankTransaction).where(BankTransaction.status == "suggested")
                             .order_by(BankTransaction.booked_on))):  # fmt: skip
        s.refresh(tx)
        if tx.status == "suggested" and (tx.suggestion_json or {}).get("confidence") == "high":
            try:
                accept(s, tx)
                n += 1
            except (DomainError, Conflict):
                s.rollback()
    return n


def ignore(s: Session, tx: BankTransaction) -> None:
    if tx.status == "matched":
        raise Conflict("bank.decided", "Undo the match first.")
    tx.status, tx.decided_at = "ignored", utcnow()
    rematch(s)
    s.commit()


def undo(s: Session, tx: BankTransaction) -> None:
    """Unmatch (removes the payments it recorded) or un-ignore."""
    if tx.status == "matched":
        for pid in tx.payment_ids or []:
            if s.get(Payment, pid) is not None:
                payments.delete_payment(s, pid, commit=False)
        tx.payment_ids = []
    elif tx.status != "ignored":
        raise Conflict("bank.not_decided", "There is nothing to undo.")
    tx.status, tx.decided_at = "unmatched", None
    rematch(s)
    core.audit(s, "bank.undone", transaction_id=tx.id)
    s.commit()


def as_dict(tx: BankTransaction) -> dict[str, Any]:
    return {
        "id": tx.id,
        "booked_on": tx.booked_on,
        "amount": str(tx.amount),
        "description": tx.description,
        "status": tx.status,
        "suggestion": tx.suggestion_json,
        "payment_ids": tx.payment_ids or [],
        "source_name": tx.source_name,
    }


def listing(s: Session, status: str | None = None) -> list[BankTransaction]:
    stmt = select(BankTransaction).order_by(BankTransaction.booked_on.desc())
    if status:
        stmt = stmt.where(BankTransaction.status == status)
    return list(s.scalars(stmt.limit(500)))
