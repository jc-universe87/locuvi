# Proposed data entities

Use UUID primary keys internally; `created_at`/`updated_at` timestamps (UTC), audit fields and schema migration history. Quantities and monetary amounts stored as exact decimal strings or fixed minor units; no float.

## OwnerProfile (singleton)
legal_name, trading_name(nullable), designation, address lines, postcode, email, phone(optional), bank_account_holder, bank_sort_code, bank_account_number, vat_status, payment_terms_days, invoice_prefix, next_invoice_number.

## Practice
id, name, billing_address, billing_email, contact_name, reference(optional), default_rate, default_unit, default_pensionable(bool), default_payment_terms_days, is_archived.

## Invoice
id, status(draft|issued|voided), invoice_number(nullable draft), practice_id, invoice_date, due_date, work_start_date, work_end_date, reference(optional), notes(optional), currency(GBP), fee_subtotal, pensionable_basic_total, pensionable_pay, employer_rate, employer_contribution, vat_amount(nullable), grand_total, issued_at, voided_at, void_reason, immutable_snapshot_json, local_pdf_path, local_pdf_sha256, local_pdf_size, issue_idempotency_key. Issued snapshot includes legal party names/addresses, bank remittance, totals, policy and presentation.

## InvoiceLine
id, invoice_id, service_date, description, unit(enum), quantity, unit_price, amount, pensionable(bool), sort_order.

## InvoiceEvent
id, invoice_id, timestamp, event_type, metadata_without_secrets.

## StorageConfig
id, enabled, target_url, username, base_path, auto_upload, secret_reference_or_encrypted_ciphertext, updated_at. Never store plain-text password in DB. Encryption key outside DB; encrypt before insert if UI saves credential.

## ArchiveJob
id, invoice_id, destination_path_snapshot, status(not_configured|pending|uploading|synced|failed|conflict), attempt_count, next_retry_at, last_attempt_at, last_error_class, remote_etag(optional), verified_sha256(optional), created_at, updated_at. Unique per invoice + destination; retain history when configuration changes.

## Numbering
Singleton InvoiceSequence or locked profile row, prefix, next_counter; unique constraint on invoice number; transaction/idempotency enforcement and tests on duplicate concurrent issue requests.

## Invariants
- Draft invoice has no official number and can change.
- Issued/voided invoice contains a frozen snapshot and a retrievable original PDF.
- Each invoice line belongs to exactly one invoice.
- Archive status never decides whether invoice is legally issued.
- No reusing invoice numbers or silent overwrite of PDF content.
- Changes to sender/practice/bank settings apply only to future issues.
- Archive jobs reference checksum of exact issued PDF.
