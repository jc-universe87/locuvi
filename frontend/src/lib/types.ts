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
  unit_prices?: string[];
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
  /** rate agreed including the employer pension; unit_price (the fee) is derived from it */
  agreed_rate?: string | null;
}

export interface PaymentState {
  state: "unpaid" | "part_paid" | "paid" | "overdue" | "credited" | "refund_due" | "n/a";
  credited?: string;
  refund_due?: string;
  paid: string | null;
  outstanding: string | null;
  days_overdue: number;
  paid_on?: string | null;
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
  payment: PaymentState;
  last_emailed_at: string | null;
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
  payments: { id: string; paid_on: string; amount: string; method: string; reference: string | null }[];
  events: { timestamp: string; event_type: string; metadata: Record<string, unknown> }[];
  credit_notes?: { id: string; number: string; credit_date: string; reason: string; grand_total: string; line_ids: string[]; archive?: string }[];
  correspondence?: (
    | { type: "sent"; at: string; to: string[]; subject: string | null }
    | { type: "document"; at: string; id: string; title: string; kind: DocKind; source: string }
  )[];
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
  hourly_rate: string | null;
  default_hours: string | null;
  default_pensionable: boolean;
  rate_includes_pension: boolean;
  default_payment_terms_days: number | null;
  is_archived: boolean;
  practice_code: string | null;
  po_required: boolean;
  invoice_instructions: string | null;
  form_a_signatory: string | null;
}

export interface Branding {
  has_logo: boolean;
  logo_format: "svg" | "png" | null;
  logo_sha256: string | null;
  accent: string;
  accents: Record<string, string>;
  invoice_footer: string;
  email_signoff: string;
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
  professional_number: string | null;
  pension_ref: string | null;
  employee_rate: string | null;
  setup_completed: boolean;
  digest_enabled: boolean;
  last_digest_sent_at: string | null;
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

export interface WorkSession {
  id: string;
  practice_id: string;
  practice_name: string;
  date: string;
  unit: Unit;
  quantity: string;
  rate: string;
  rate_includes_pension: boolean;
  pensionable: boolean;
  description: string;
  status: "active" | "cancelled";
  invoice: { id: string; status: InvoiceStatus; invoice_number: string | null } | null;
}

export interface ReadyGroup {
  practice_id: string;
  practice_name: string;
  month: string;
  sessions: number;
  total: string;
}

export interface Overview {
  today: string;
  greeting_name: string;
  setup: { completed: boolean; profile: boolean; practice: boolean };
  ready_to_invoice: ReadyGroup[];
  drafts: { id: string; practice_name: string | null; grand_total: string | null; work_start_date: string | null; work_end_date: string | null }[];
  unpaid: { id: string; invoice_number: string; practice_name: string; due_date: string; outstanding: string; state: PaymentState["state"]; days_overdue: number }[];
  outstanding_total: string;
  overdue_count: number;
  pension_due: PensionMonth[];
  upcoming: { id: string; date: string; unit: Unit; practice_name: string }[];
  this_month_invoiced: string;
  findings: Finding[];
  tax_year: { invoiced: string; paid: string; outstanding: string; employer: string; fees: string };
}

export interface PensionMonth {
  month: string;
  practices: number;
  pensionable_pay: string;
  employer: string;
  employee: string | null;
  submitted_on: string | null;
  changed_since_submitted: boolean;
  ready: boolean;
  forms_a_signed: number;
  pcse: "none" | "match" | "mismatch";
  work_pay: string;
  received_items: number;
  due_by: string;
}

export interface EmailConfig {
  enabled: boolean;
  host: string;
  port: number;
  security: "starttls" | "ssl";
  username: string;
  from_address: string;
  from_name: string;
  bcc_self: boolean;
  password_set: boolean;
}

export interface Finding {
  key: string;
  kind: string;
  severity: "urgent" | "warn" | "info";
  params: Record<string, string | number | null>;
  ref: { type: string; id: string } | null;
  action:
    | { type: "create_invoice"; practice_id: string; month: string }
    | { type: "open_draft" | "open_invoice"; invoice_id: string }
    | { type: "mark_paid"; invoice_id: string; number: string }
    | { type: "open_diary"; date: string }
    | { type: "open_pension"; month: string }
    | { type: "open_settings"; section: string }
    | { type: "backup_now" }
    | { type: "open_inbox" }
    | { type: "open_bank" }
    | null;
  dismissible: boolean;
}

export type DocKind = "booking" | "remittance" | "statement" | "pension" | "other";

export interface Doc {
  id: string;
  kind: DocKind;
  title: string;
  source: "upload" | "paste";
  filename: string | null;
  content_type: string | null;
  size: number;
  status: "new" | "done";
  practice_id: string | null;
  invoice_id: string | null;
  has_file: boolean;
  has_text: boolean;
  excerpt: string;
  created_at: string;
  deleted: boolean;
  text?: string;
  proposals?: Proposal[];
}

export type ProposalFlag = "needs_practice" | "needs_rate" | "duplicate" | "rate_differs" | "clash" | "not_in_diary" | "invoiced";

export interface ProposalItem {
  date: string;
  unit: "am" | "pm" | "day" | "hours";
  hours: string | null;
  practice_id: string | null;
  practice_name: string | null;
  rate: string | null;
  rate_source: "text" | "remembered" | null;
  action: "add" | "cancel";
  note: string | null;
  flags: ProposalFlag[];
  clash_with: string | null;
  diary_rate: string | null;
  session_id: string | null;
  past: boolean;
  selected: boolean;
}

export interface Proposal {
  id: string;
  kind: string;
  document_id: string | null;
  status: "pending" | "accepted" | "partial" | "rejected" | "verified";
  engine: string;
  ai: boolean;
  summary: string;
  items: ProposalItem[];
  questions: string[];
  result: { applied: number[]; created: string[]; cancelled: string[] } | null;
  created_at: string;
}

export interface AiProvider {
  id: string;
  label: string;
  default_model: string;
  key_url: string;
  reads_photos: boolean;
}

export interface AssistantConfig {
  enabled: boolean;
  provider: string;
  model: string;
  model_custom: boolean;
  reads_photos: boolean;
  providers: AiProvider[];
  key_saved: boolean;
  key_from_server: boolean;
  ready: boolean;
  weekly_brief: boolean;
}

export interface ScanResult {
  checked: number;
  skipped: number;
  already_seen: number;
  bookings: number;
  remittances: number;
  already_booked: number;
  to_review: number;
  unread: number;
  folder_errors: number;
  /** accounts that couldn't be checked (the others still were) */
  errors?: { account_id: number; label: string; error: string }[];
}

export interface MailboxConfig {
  id: number;
  label: string;
  enabled: boolean;
  provider: "imap" | "microsoft";
  ms_client_id: string;
  ms_tenant: string;
  ms_signed_in: boolean;
  folder_labels: Record<string, string>;
  host: string;
  port: number;
  security: "ssl" | "starttls";
  username: string;
  password_set: boolean;
  folders: string[];
  since_days: number;
  auto_scan: boolean;
  last_scan_at: string | null;
  last_error: string | null;
  last_result: ScanResult | null;
}

export interface BankTx {
  id: string;
  booked_on: string;
  amount: string;
  description: string;
  status: "suggested" | "unmatched" | "matched" | "ignored";
  suggestion: {
    kind: "number" | "amount" | "amount_practice" | "combined";
    confidence: "high" | "medium";
    invoices: { id: string; number: string; practice: string; amount: string }[];
  } | null;
  payment_ids: string[];
  source_name: string;
}

export interface HouseholdProfile {
  id: number;
  name: string;
  is_admin: boolean;
  password_set: boolean;
  created_at: string;
  deleted_at: string | null;
}
