import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { BookingSheet, ProposalReview, useAssistant, usePractices } from "../components/Booking";
import { Dialog, ErrorAlert, Icon, PageHead, Segmented, useToast } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, ApiError, downloadBlob } from "../lib/api";
import { ukDate } from "../lib/format";
import type { Doc, DocKind, InvoiceSummary, MailboxConfig, Proposal, ScanResult } from "../lib/types";

const KINDS: DocKind[] = ["booking", "remittance", "statement", "pension", "other"];
const KIND_ICON: Record<DocKind, string> = {
  booking: "diary", remittance: "money", statement: "reports", pension: "pension", other: "invoices",
};
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.txt,.csv,.eml,application/pdf,image/png,image/jpeg,text/plain,text/csv,message/rfc822";

type Filter = "new" | "done";

type T = ReturnType<typeof useT>["t"];
type TN = ReturnType<typeof useT>["tn"];

/** "Checked 12 emails · 2 bookings to check · 1 already in your diary" */
export function scanSummary(t: T, tn: TN, r: ScanResult): string {
  const parts = [tn("mailbox.res_checked", r.checked)];
  if (r.to_review) parts.push(tn("mailbox.res_review", r.to_review));
  if (r.already_booked) parts.push(tn("mailbox.res_booked", r.already_booked));
  if (r.remittances) parts.push(tn("mailbox.res_remittances", r.remittances));
  if (r.checked && !r.to_review && !r.already_booked && !r.remittances) parts.push(t("mailbox.res_nothing"));
  return parts.join(" · ");
}

export default function InboxPage() {
  const { t, tn } = useT();
  const toast = useToast();
  const practices = usePractices();
  const [filter, setFilter] = useState<Filter>("new");
  const [q, setQ] = useState("");
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [pending, setPending] = useState<Proposal[]>([]);
  const [open, setOpen] = useState<Doc | null>(null);
  const [review, setReview] = useState<Proposal | null>(null);
  const [pasting, setPasting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    const id = params.get("doc");
    if (!id) return;
    api.get<Doc>(`/documents/${id}`).then(setOpen, setError);
    setParams({}, { replace: true });
  }, [params, setParams]);
  const [mailboxOn, setMailboxOn] = useState(false);
  const [scanning, setScanning] = useState(false);
  useEffect(() => {
    api.get<MailboxConfig>("/settings/mailbox").then((m) => setMailboxOn(m.enabled), () => undefined);
  }, []);
  const checkEmail = async () => {
    setScanning(true);
    setError(null);
    try {
      const r = await api.post<ScanResult>("/mailbox/scan");
      toast({ text: scanSummary(t, tn, r) });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setScanning(false);
    }
  };

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ status: filter });
      if (q.trim()) params.set("q", q.trim());
      const [d, p] = await Promise.all([
        api.get<{ documents: Doc[] }>(`/documents?${params}`),
        api.get<Proposal[]>("/proposals"),
      ]);
      setDocs(d.documents);
      setPending(p);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [filter, q]);
  useEffect(() => {
    const id = setTimeout(load, 120);
    return () => clearTimeout(id);
  }, [load]);

  const upload = async (files: FileList | File[]) => {
    setError(null);
    let added = 0;
    for (const f of Array.from(files).slice(0, 20)) {
      const form = new FormData();
      form.append("file", f, f.name);
      try {
        await api.upload<Doc>("/documents", form);
        added += 1;
      } catch (e) {
        setError(e);
      }
    }
    if (added) toast({ text: tn("inbox.added", added) });
    setFilter("new");
    await load();
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) void upload(e.dataTransfer.files);
  };
  const practiceName = (id: string | null) => practices.find((p) => p.id === id)?.name;

  return (
    <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
      className={dragging ? "dropping" : undefined}>
      <PageHead title={t("inbox.title")}>
        {mailboxOn && (
          <button className="btn secondary small" disabled={scanning} onClick={checkEmail}>
            <Icon name="send" size={16} /> {scanning ? t("mailbox.checking") : t("mailbox.check_now")}
          </button>
        )}
        <button className="btn secondary small" onClick={() => fileInput.current?.click()}>
          <Icon name="upload" size={16} /> {t("inbox.add_file")}
        </button>
        <button className="btn small" onClick={() => setPasting(true)}>
          <Icon name="paste" size={16} /> {t("booking.open")}
        </button>
      </PageHead>
      <input ref={fileInput} type="file" multiple accept={ACCEPT} hidden aria-label={t("inbox.add_file")}
        onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = ""; }} />
      <ErrorAlert error={error} />

      {pending.length > 0 && (
        <section className="card flush" aria-labelledby="sugg-h">
          <h2 id="sugg-h" className="card-pad-title">{t("inbox.suggestions")}</h2>
          {pending.map((p) => (
            <button key={p.id} className="list-row" onClick={() => setReview(p)}>
              <span className="task-icon"><Icon name={p.ai ? "sparkle" : "diary"} /></span>
              <span className="list-main">
                <span className="list-title">{p.summary || tn("inbox.suggestion_items", p.items.length)}</span>
                <span className="list-sub">{tn("inbox.suggestion_items", p.items.length)} · {ukDate(p.created_at.slice(0, 10))}</span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </button>
          ))}
        </section>
      )}

      <div className="row wrap" style={{ marginBottom: "0.9rem" }}>
        <Segmented<Filter> value={filter} onChange={setFilter} label={t("inbox.filter")}
          options={[{ value: "new", label: t("inbox.filter_new") }, { value: "done", label: t("inbox.filter_done") }]} />
        <span className="spacer" />
        <label className="sr-only" htmlFor="inbox-q">{t("common.search")}</label>
        <input id="inbox-q" type="search" value={q} placeholder={t("inbox.search_placeholder")}
          style={{ maxWidth: "18rem", background: "var(--card)" }} onChange={(e) => setQ(e.target.value)} />
      </div>

      {docs && docs.length === 0 && (
        <div className="card empty">
          <div className="big" aria-hidden="true">📥</div>
          <p>{q ? t("inbox.none_match") : filter === "new" ? t("inbox.empty") : t("inbox.empty_done")}</p>
          {!q && filter === "new" && <p className="faint">{t("inbox.drop_hint")}</p>}
        </div>
      )}
      {docs && docs.length > 0 && (
        <div className="card flush">
          {docs.map((d) => (
            <button key={d.id} className="list-row" onClick={() => api.get<Doc>(`/documents/${d.id}`).then(setOpen, setError)}>
              <span className="task-icon"><Icon name={KIND_ICON[d.kind]} /></span>
              <span className="list-main">
                <span className="list-title">{d.title}</span>
                <span className="list-sub">
                  {t(`inbox.kind_${d.kind}` as MessageKey)} · {ukDate(d.created_at.slice(0, 10))}
                  {practiceName(d.practice_id) ? ` · ${practiceName(d.practice_id)}` : ""}
                </span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </button>
          ))}
        </div>
      )}

      <DocSheet doc={open} practices={practices} onClose={() => setOpen(null)} onChanged={load}
        onProposal={(p) => { setOpen(null); setReview(p); }} />
      <BookingSheet open={pasting} onClose={() => setPasting(false)} onChanged={load} />
      <Dialog open={review !== null} onClose={() => setReview(null)} title={t("booking.review_title")}>
        {review && <ProposalReview proposal={review} practices={practices} onDone={() => { setReview(null); void load(); }} />}
      </Dialog>
    </div>
  );
}

function DocSheet({
  doc,
  practices,
  onClose,
  onChanged,
  onProposal,
}: {
  doc: Doc | null;
  practices: { id: string; name: string }[];
  onClose: () => void;
  onChanged: () => void;
  onProposal: (p: Proposal) => void;
}) {
  const { t } = useT();
  const toast = useToast();
  const assistant = useAssistant();
  const [d, setD] = useState<Doc | null>(doc);
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  useEffect(() => {
    if (doc) api.get<{ items: InvoiceSummary[] }>("/invoices?status=issued&page_size=100").then((r) => setInvoices(r.items), () => undefined);
  }, [doc]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  useEffect(() => {
    setD(doc);
    setError(null);
    setConsent(false);
  }, [doc]);
  if (!d) return <Dialog open={false} onClose={onClose} title="">{null}</Dialog>;

  const patch = async (body: Partial<Pick<Doc, "kind" | "status" | "practice_id" | "invoice_id">>) => {
    try {
      const next = await api.patch<Doc>(`/documents/${d.id}`, body);
      setD({ ...d, ...next });
      onChanged();
    } catch (e) {
      setError(e);
    }
  };
  const read = async (sendAttachment = false) => {
    setBusy(true);
    setError(null);
    try {
      onProposal(await api.post<Proposal>(`/documents/${d.id}/read`, { send_attachment: sendAttachment }));
      setConsent(false);
      onChanged();
    } catch (e) {
      // A scan/photo can't be redacted: ask before the file itself leaves Locuvi.
      if (e instanceof ApiError && e.body.code === "assistant.attachment_consent") setConsent(true);
      else setError(e);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    try {
      await api.del(`/documents/${d.id}`);
      onClose();
      onChanged();
      toast({
        text: t("inbox.deleted"),
        undo: () => void api.post(`/documents/${d.id}/restore`).then(onChanged, () => undefined),
      });
    } catch (e) {
      setError(e);
    }
  };
  const download = async () => {
    try {
      downloadBlob(await api.blob("GET", `/documents/${d.id}/file`), d.filename ?? "document");
    } catch (e) {
      setError(e);
    }
  };
  const canRead = d.has_text || (!!assistant?.ready && d.has_file && /pdf|image/.test(d.content_type ?? ""));
  const latest = d.proposals?.[0];

  return (
    <Dialog open onClose={onClose} title={d.title}
      footer={
        <div className="actions" style={{ width: "100%" }}>
          {d.kind === "booking" && canRead && (
            <button className="btn" disabled={busy} onClick={() => void read()}>
              <Icon name={assistant?.ready ? "sparkle" : "diary"} size={16} /> {busy ? t("booking.reading") : t("inbox.read_booking")}
            </button>
          )}
          {d.has_file && <button className="btn secondary" onClick={download}><Icon name="download" size={16} /> {t("inbox.download")}</button>}
          <span className="spacer" />
          <button className="btn ghost" onClick={remove} aria-label={t("inbox.delete")}><Icon name="trash" size={18} /></button>
        </div>
      }>
      <ErrorAlert error={error} />
      {consent && (
        <div className="alert warn" role="alertdialog" aria-label={t("inbox.consent_title")}>
          <strong>{t("inbox.consent_title")}</strong>
          <p style={{ margin: "0.4rem 0 0.6rem" }}>{t("inbox.consent_text")}</p>
          <div className="actions">
            <button className="btn small" disabled={busy} onClick={() => void read(true)}>{t("inbox.consent_send")}</button>
            <button className="btn ghost small" onClick={() => setConsent(false)}>{t("common.cancel")}</button>
          </div>
        </div>
      )}
      <div className="form-list">
        <div className="form-row">
          <label htmlFor="doc-kind">{t("inbox.kind")}</label>
          <select id="doc-kind" value={d.kind} onChange={(e) => void patch({ kind: e.target.value as DocKind })}>
            {KINDS.map((k) => <option key={k} value={k}>{t(`inbox.kind_${k}` as MessageKey)}</option>)}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="doc-practice">{t("booking.practice")}</label>
          <select id="doc-practice" value={d.practice_id ?? ""} onChange={(e) => void patch({ practice_id: e.target.value || null })}>
            <option value="">—</option>
            {practices.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="form-row">
          <label htmlFor="doc-invoice">{t("corr.invoice")}</label>
          <select id="doc-invoice" value={d.invoice_id ?? ""} onChange={(e) => void patch({ invoice_id: e.target.value || null })}>
            <option value="">—</option>
            {invoices.map((i) => <option key={i.id} value={i.id}>{i.invoice_number} · {i.practice_name}</option>)}
          </select>
        </div>
        <div className="form-row" style={{ gridTemplateColumns: "1fr auto" }}>
          <span>{d.status === "done" ? t("inbox.is_done") : t("inbox.is_new")}</span>
          <button className="btn secondary small" onClick={() => void patch({ status: d.status === "done" ? "new" : "done" })}>
            {d.status === "done" ? t("inbox.mark_new") : t("inbox.mark_done")}
          </button>
        </div>
      </div>
      {latest && latest.status !== "pending" && (
        <p className="muted">{t(`inbox.proposal_${latest.status}` as MessageKey)}</p>
      )}
      {d.text ? (
        <pre className="doc-text">{d.text}</pre>
      ) : (
        <p className="muted">{t("inbox.no_text")}</p>
      )}
    </Dialog>
  );
}
