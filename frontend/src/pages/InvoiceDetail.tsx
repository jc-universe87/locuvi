import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArchivePill, Dialog, ErrorAlert, Field, Icon, InvoicePill, useToast } from "../components/ui";
import { hasKey, useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, downloadBlob } from "../lib/api";
import { dateTime, gbp, pct, period, todayLondon, ukDate } from "../lib/format";
import type { ArchiveStatus, InvoiceDetail } from "../lib/types";

export default function InvoiceDetailPage() {
  const { t } = useT();
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const location = useLocation();
  const issuedNumber = (location.state as { issued?: string } | null)?.issued;
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sheet, setSheet] = useState<null | "void" | "email" | "pay" | "more">(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get<InvoiceDetail>(`/invoices/${id}`);
      if (d.status === "draft") nav(`/invoices/${id}/edit`, { replace: true });
      else setInv(d);
    } catch (e) {
      setError(e);
    }
  }, [id, nav]);

  useEffect(() => {
    void load();
  }, [load]);

  // Keep the archive status truthful while an upload is in flight.
  useEffect(() => {
    if (!inv || !["pending", "uploading"].includes(inv.archive.status) || !inv.archive.webdav_enabled) return;
    const h = setInterval(async () => {
      try {
        const a = await api.get<ArchiveStatus>(`/invoices/${inv.id}/archive-status`);
        setInv((cur) => (cur ? { ...cur, archive: a } : cur));
      } catch {
        /* ignore */
      }
    }, 4000);
    return () => clearInterval(h);
  }, [inv]);

  if (error && !inv) return <ErrorAlert error={error} />;
  if (!inv) return null;

  const snap = inv.snapshot;
  const totals = snap?.totals;
  const a = inv.archive;
  const pay = inv.payment;
  const unpaid = inv.status === "issued" && pay.state !== "paid";

  const download = async () => {
    try {
      downloadBlob(await api.blob("GET", `/invoices/${inv.id}/pdf`), `${inv.invoice_number}.pdf`);
    } catch (e) {
      setError(e);
    }
  };
  const markPaid = async () => {
    try {
      const d = await api.post<InvoiceDetail>(`/invoices/${inv.id}/payments`, {});
      setInv(d);
      const pid = d.payments[d.payments.length - 1]?.id;
      toast({
        text: t("pay.marked_paid", { number: inv.invoice_number ?? "" }),
        undo: pid ? async () => setInv(await api.del(`/payments/${pid}`).then(() => api.get<InvoiceDetail>(`/invoices/${inv.id}`))) : undefined,
      });
    } catch (e) {
      setError(e);
    }
  };
  const removePayment = async (pid: string) => {
    try {
      setInv(await api.del(`/payments/${pid}`).then(() => api.get<InvoiceDetail>(`/invoices/${inv.id}`)));
    } catch (e) {
      setError(e);
    }
  };
  const retry = async () => {
    setBusy(true);
    try {
      const st = await api.post<ArchiveStatus>(`/invoices/${inv.id}/archive-retry`);
      setInv({ ...inv, archive: st });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const duplicate = async () => {
    try {
      const d = await api.post<InvoiceDetail>(`/invoices/${inv.id}/duplicate`);
      nav(`/invoices/${d.id}/edit`);
    } catch (e) {
      setError(e);
    }
  };

  const errKey = a.last_error_class ? `archive_error.${a.last_error_class}` : null;

  return (
    <>
      <p style={{ margin: "0.5rem 0 0" }}>
        <Link to="/invoices" className="btn ghost small"><Icon name="back" size={16} /> {t("nav.invoices")}</Link>
      </p>
      {issuedNumber && <div className="alert ok" role="status">{t("issue.done", { number: issuedNumber })}</div>}
      <ErrorAlert error={error} />

      <div className="inv-hero">
        <div className="meta">{snap?.bill_to.name}</div>
        <div className="amount">{gbp(totals?.grand_total)}</div>
        <div className="row" style={{ justifyContent: "center", gap: "0.4rem" }}>
          <span className="meta">{inv.invoice_number}</span>
          <InvoicePill status={inv.status} payment={pay} due={inv.due_date} />
        </div>
        {pay.state === "part_paid" || (pay.state === "overdue" && pay.paid !== "0.00") ? (
          <p className="muted" style={{ margin: "0.4rem 0 0" }}>{t("pay.outstanding", { amount: gbp(pay.outstanding) })}</p>
        ) : null}
        {inv.last_emailed_at && <p className="hint" style={{ margin: "0.3rem 0 0" }}>{t("email.sent_on", { when: dateTime(inv.last_emailed_at) })}</p>}
      </div>

      {inv.status === "voided" && (
        <div className="alert warn">{t("detail.voided", { date: dateTime(inv.voided_at), reason: inv.void_reason ?? "" })}</div>
      )}

      <div className="big-actions">
        <button className="btn" onClick={download}><Icon name="download" />{t("detail.download_short")}</button>
        {inv.status === "issued" && (
          <button className="btn" onClick={() => setSheet("email")}><Icon name="send" />{t("email.send_short")}</button>
        )}
        {unpaid && (
          <button className="btn primary" onClick={markPaid}><Icon name="check" />{t("pay.mark_paid")}</button>
        )}
        <button className="btn" onClick={() => setSheet("more")}><Icon name="more" />{t("common.more")}</button>
      </div>

      <section className="card">
        <dl className="kv">
          <dt>{t("detail.bill_to")}</dt>
          <dd>{snap?.bill_to.name}{snap?.bill_to.address_lines.length ? <span className="muted">, {snap.bill_to.address_lines.join(", ")}</span> : null}</dd>
          <dt>{t("editor.issue_date")}</dt><dd>{ukDate(inv.invoice_date)}</dd>
          <dt>{t("editor.due_date")}</dt><dd>{ukDate(inv.due_date)}</dd>
          <dt>{t("invoices.col_period")}</dt><dd>{period(inv.work_start_date, inv.work_end_date)}</dd>
          {inv.reference && (<><dt>{t("editor.reference")}</dt><dd>{inv.reference}</dd></>)}
        </dl>
      </section>

      <section className="card flush">
        <ul className="list">
          {inv.lines.map((l) => (
            <li key={l.id}>
              <span className="list-main">
                <span className="list-title">{l.description}</span>
                <span className="list-sub">
                  {ukDate(l.service_date)} · {t(`unit.${l.unit}` as MessageKey)}
                  {l.quantity !== "1" && l.quantity !== "1.00" ? ` × ${l.quantity}` : ""}
                  {inv.pension_enabled && l.pensionable ? ` · ${t("detail.pensionable_short")}` : ""}
                </span>
              </span>
              <span className="money">{gbp(l.amount)}</span>
            </li>
          ))}
          {totals && totals.employer_rate && totals.pensionable_basic_total !== "0.00" && (
            <li>
              <span className="list-main">
                <span className="list-title">{t("totals.employer", { rate: pct(totals.employer_rate) })}</span>
                <span className="list-sub">{t("totals.pensionable_pay", { fraction: pct(totals.pensionable_fraction) })}: {gbp(totals.pensionable_pay)}</span>
              </span>
              <span className="money">{gbp(totals.employer_contribution)}</span>
            </li>
          )}
          <li>
            <span className="list-main"><span className="list-title">{t("totals.total")}</span></span>
            <span className="money" style={{ fontWeight: 700 }}>{gbp(totals?.grand_total)}</span>
          </li>
        </ul>
      </section>

      {inv.payments.length > 0 && (
        <section className="card flush" aria-labelledby="h-pay">
          <h2 id="h-pay" style={{ padding: "0.9rem 1.15rem 0", margin: 0 }}>{t("pay.payments")}</h2>
          <ul className="list">
            {inv.payments.map((p) => (
              <li key={p.id}>
                <span className="list-main">
                  <span className="list-title">{gbp(p.amount)}</span>
                  <span className="list-sub">{ukDate(p.paid_on)} · {t(`pay.method_${p.method}` as MessageKey)}{p.reference ? ` · ${p.reference}` : ""}</span>
                </span>
                <button className="btn ghost small" onClick={() => removePayment(p.id)}>{t("common.remove")}</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(a.webdav_enabled || a.status === "synced") && (
        <section className="card">
          <div className="row">
            <Icon name="cloud" />
            <span className="list-main">
              <span className="list-title">{t("detail.archive")}</span>
              {a.remote_path && <span className="list-sub mono">{decodeURIComponent(a.remote_path)}</span>}
            </span>
            <ArchivePill archive={a} />
          </div>
          {(a.status === "failed" || a.status === "conflict") && (
            <div className="alert error" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
              {a.status === "conflict" ? t("archive.conflict_help") : errKey && hasKey(errKey) ? t(errKey as MessageKey) : a.last_error_class}
              {a.retry_paused && a.status === "failed" && <div>{t("archive.paused")}</div>}
              {!a.retry_paused && a.next_retry_at && <div>{t("archive.next_retry", { when: dateTime(a.next_retry_at) })}</div>}
            </div>
          )}
          {a.webdav_enabled && a.status !== "synced" && a.status !== "uploading" && (
            <button className="btn secondary small" style={{ marginTop: "0.75rem" }} onClick={retry} disabled={busy}>
              {a.status === "not_configured" ? t("archive.upload_now") : t("archive.retry")}
            </button>
          )}
        </section>
      )}

      {inv.correspondence && inv.correspondence.length > 0 && (
        <section className="card flush" aria-labelledby="h-corr">
          <h2 id="h-corr" className="card-pad-title">{t("corr.title")}</h2>
          {inv.correspondence.map((c, i) => c.type === "sent" ? (
            <div key={i} className="list-row">
              <span className="task-icon ok"><Icon name="send" size={18} /></span>
              <span className="list-main">
                <span className="list-title">{c.subject ?? t("corr.sent")}</span>
                <span className="list-sub">{t("corr.sent_to", { to: c.to.join(", "), when: dateTime(c.at) })}</span>
              </span>
            </div>
          ) : (
            <Link key={i} to={`/inbox?doc=${c.id}`} className="list-row">
              <span className="task-icon"><Icon name="inbox" size={18} /></span>
              <span className="list-main">
                <span className="list-title">{c.title}</span>
                <span className="list-sub">{t(`inbox.kind_${c.kind}` as MessageKey)} · {dateTime(c.at)}</span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </Link>
          ))}
        </section>
      )}

      <details className="more card">
        <summary>{t("detail.history")}</summary>
        <ul className="timeline" style={{ marginTop: "0.5rem" }}>
          {inv.events.map((e, i) => (
            <li key={i}>
              <time dateTime={e.timestamp}>{dateTime(e.timestamp)}</time>
              {hasKey(`event.${e.event_type}`) ? t(`event.${e.event_type}` as MessageKey) : e.event_type}
              {typeof e.metadata.error_class === "string" && hasKey(`archive_error.${e.metadata.error_class}`) && (
                <span className="muted"> — {t(`archive_error.${e.metadata.error_class}` as MessageKey)}</span>
              )}
            </li>
          ))}
        </ul>
        <p className="mono" style={{ marginTop: "0.75rem" }}>{t("detail.checksum")}: {inv.local_pdf_sha256}</p>
      </details>

      <Dialog open={sheet === "more"} title={inv.invoice_number ?? ""} onClose={() => setSheet(null)}>
        <div className="grid">
          {unpaid && <button className="btn secondary block" onClick={() => setSheet("pay")}>{t("pay.record_other")}</button>}
          <button className="btn secondary block" onClick={duplicate}><Icon name="copy" size={18} /> {t("detail.duplicate")}</button>
          {a.webdav_enabled && a.status === "synced" && (
            <button className="btn secondary block" onClick={retry}>{t("archive.reverify")}</button>
          )}
          {inv.status === "issued" && inv.payments.length === 0 && (
            <button className="btn danger block" onClick={() => setSheet("void")}>{t("detail.void")}</button>
          )}
          <p className="hint" style={{ textAlign: "center" }}>{t("detail.immutable")}</p>
        </div>
      </Dialog>
      {sheet === "void" && <VoidSheet inv={inv} onClose={() => setSheet(null)} onDone={(d) => { setInv(d); setSheet(null); }} />}
      {sheet === "email" && <EmailSheet inv={inv} onClose={() => setSheet(null)} onSent={() => { setSheet(null); toast({ text: t("email.sent") }); void load(); }} />}
      {sheet === "pay" && <PaySheet inv={inv} onClose={() => setSheet(null)} onDone={(d) => { setInv(d); setSheet(null); }} />}
    </>
  );
}

function VoidSheet({ inv, onClose, onDone }: { inv: InvoiceDetail; onClose: () => void; onDone: (d: InvoiceDetail) => void }) {
  const { t } = useT();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog open title={t("detail.void_title")} onClose={onClose}
      footer={<button className="btn danger" disabled={!reason.trim()} onClick={async () => {
        try {
          onDone(await api.post<InvoiceDetail>(`/invoices/${inv.id}/void`, { reason }));
        } catch (e) {
          setError(e);
        }
      }}>{t("detail.void")}</button>}>
      <ErrorAlert error={error} />
      <p style={{ marginTop: 0 }}>{t("detail.void_body")}</p>
      <Field id="void-reason" label={t("detail.void_reason")}>
        <textarea id="void-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} autoFocus />
      </Field>
    </Dialog>
  );
}

function PaySheet({ inv, onClose, onDone }: { inv: InvoiceDetail; onClose: () => void; onDone: (d: InvoiceDetail) => void }) {
  const { t } = useT();
  const [amount, setAmount] = useState(inv.payment.outstanding ?? "");
  const [paidOn, setPaidOn] = useState(todayLondon());
  const [method, setMethod] = useState("bank_transfer");
  const [error, setError] = useState<unknown>(null);
  return (
    <Dialog open title={t("pay.record_other")} onClose={onClose}
      footer={<button className="btn" onClick={async () => {
        try {
          onDone(await api.post<InvoiceDetail>(`/invoices/${inv.id}/payments`, { amount, paid_on: paidOn, method }));
        } catch (e) {
          setError(e);
        }
      }}>{t("common.save")}</button>}>
      <ErrorAlert error={error} />
      <div className="grid grid-2">
        <Field id="pay-amount" label={t("pay.amount")}>
          <input id="pay-amount" type="text" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field id="pay-date" label={t("pay.date")}>
          <input id="pay-date" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
        <Field id="pay-method" label={t("pay.method")} className="span-2">
          <select id="pay-method" value={method} onChange={(e) => setMethod(e.target.value)}>
            {["bank_transfer", "cheque", "cash", "other"].map((m) => <option key={m} value={m}>{t(`pay.method_${m}` as MessageKey)}</option>)}
          </select>
        </Field>
      </div>
    </Dialog>
  );
}

function EmailSheet({ inv, onClose, onSent }: { inv: InvoiceDetail; onClose: () => void; onSent: () => void }) {
  const { t } = useT();
  const [draft, setDraft] = useState<{ to: string; subject: string; body: string; configured: boolean } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<{ to: string; subject: string; body: string; configured: boolean }>(`/invoices/${inv.id}/email`).then(setDraft, setError);
  }, [inv.id]);
  const send = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      await api.post(`/invoices/${inv.id}/email`, { to: draft.to, subject: draft.subject, body: draft.body });
      onSent();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={t("email.title", { number: inv.invoice_number ?? "" })} onClose={onClose}
      footer={draft?.configured ? (
        <button className="btn" onClick={send} disabled={busy || !draft.to.trim()}><Icon name="send" size={18} /> {busy ? t("email.sending") : t("email.send")}</button>
      ) : (
        <Link className="btn" to="/settings/email">{t("email.set_up")}</Link>
      )}>
      <ErrorAlert error={error} />
      {draft && !draft.configured && <p style={{ marginTop: 0 }}>{t("email.not_configured")}</p>}
      {draft?.configured && (
        <div className="grid">
          <Field id="em-to" label={t("email.to")}>
            <input id="em-to" type="email" multiple value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </Field>
          <Field id="em-subject" label={t("email.subject")}>
            <input id="em-subject" type="text" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          </Field>
          <Field id="em-body" label={t("email.message")}>
            <textarea id="em-body" rows={8} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          </Field>
          <p className="hint" style={{ margin: 0 }}>{t("email.attachment", { file: `${inv.invoice_number}.pdf` })}</p>
        </div>
      )}
    </Dialog>
  );
}
