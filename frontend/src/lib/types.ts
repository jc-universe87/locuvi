export type Unit = "am" | "pm" | "day" | "hours" | "custom";
export type InvoiceStatus = "draft" | "issued" | "voided";
export type ArchiveState = "not_configured" | "pending" | "uploading" | "synced" | "failed" | "conflict";

export interface Issue {
  code: string;
  message: string;
  params: Record<string, unknown>;
}

export interface Totals {
  line_amounts: string[];
  fee_subtotal: string;
  non_pensionable_total: string;
  pensionable_basic_total: string;
  pensionable_pay: string;
  employer_rate: string | null;
  pensionable_fraction: string | null;
  employer_contribution: string;
  vat_amount: string | null;
  grand_total: string;
}

export interface Analysis {
  totals: Totals;
  blocking: Issue[];
  warnings: Issue[];
  work_start_date: string | null;
  work_end_date: string | null;
  policy: { id: string; label: string; effective_from: string; employer_rate: string; pensionable_fraction: string } | null;
}

export interface ArchiveStatus {
  status: ArchiveState;
  webdav_enabled: boolean;
  attempt_count?: number;
  last_attempt_at?: string | null;
  next_retry_at?: string | null;
  last_error_class?: string | null;
  remote_path?: string;
  remote_etag?: string | null;
  verified_sha256?: string | null;
  local_sha256?: string;
  retry_paused?: boolean;
}

export interface Line {
  id?: string;
  service_date: string;
  description: string;
  unit: Unit;
  quantity: string;
  unit_price: string;
  amount?: string;
  pensionable: boolean;
}

export interface InvoiceSummary {
  id: string;
  status: InvoiceStatus;
  invoice_number: string | null;
  practice_id: string | null;
  practice_name: string | null;
  invoice_date: string | null;
  due_date: string | null;
  work_start_date: string | null;
  work_end_date: string | null;
  grand_total: string | null;
  archive: ArchiveStatus;
}

export interface InvoiceDetail extends InvoiceSummary {
  reference: string | null;
  notes: string | null;
  pension_enabled: boolean;
  issued_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  local_pdf_sha256: string | null;
  lines: Line[];
  events: { timestamp: string; event_type: string; metadata: Record<string, unknown> }[];
  analysis?: Analysis;
  snapshot?: {
    seller: { legal_name: string };
    bill_to: { name: string; address_lines: string[] };
    totals: Totals;
    pension: { enabled: boolean; employer_rate: string | null; pensionable_fraction: string | null; policy_label: string | null };
    bank: { account_holder: string; sort_code: string; account_number: string };
  };
  replayed?: boolean;
}

export interface Practice {
  id: string;
  name: string;
  billing_address: string;
  billing_email: string | null;
  contact_name: string | null;
  reference: string | null;
  default_rate: string | null;
  default_unit: Unit;
  default_pensionable: boolean;
  rate_includes_pension: boolean;
  default_payment_terms_days: number | null;
  is_archived: boolean;
}

export interface Profile {
  legal_name: string;
  trading_name: string | null;
  designation: string;
  address_lines: string;
  postcode: string;
  email: string;
  phone: string | null;
  bank_account_holder: string;
  bank_sort_code: string;
  bank_account_number_masked: string;
  bank_account_number_set: boolean;
  vat_status: "not_vat_registered" | "vat_registered";
  payment_terms_days: number;
  pension_default_enabled: boolean;
}

export interface Numbering {
  prefix: string;
  next_number: number;
  padding: number;
  preview: string;
}

export interface Policy {
  id: string;
  effective_from: string;
  employer_rate: string;
  pensionable_fraction: string;
  label: string;
  source_note: string;
  in_use: boolean;
}

export interface WebDavConfig {
  enabled: boolean;
  target_url: string;
  username: string;
  base_path: string;
  auto_upload: boolean;
  password_set: boolean;
  password_source: "secret_file" | "stored" | "none";
}
