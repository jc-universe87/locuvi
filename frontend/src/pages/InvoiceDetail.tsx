import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ArchiveBadge, Dialog, ErrorAlert, Field, StatusBadge } from "../components/ui";
import { hasKey, useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, downloadBlob } from "../lib/api";
import { dateTime, gbp, pct, period, ukDate } from "../lib/format";
import type { ArchiveStatus, InvoiceDetail } from "../lib/types";

export default function InvoiceDetailPage() {
  const { t } = useT();
  const { id } = useParams();
  const nav = useNavigate();
  const location = useLocation();
  const issuedNumber = (location.state as { issued?: string } | null)?.issued;
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [voidOpen, setVoidOpen] = useState(false);
  const [reason, setReason] = useState("");
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

  // Poll while an upload is in flight so the status is shown truthfully.
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
  if (!inv) return <p className="muted">{t("app.loading")}</p>;

  const snap = inv.snapshot;
  const totals = snap?.totals;
  const a = inv.archive;

  const download = async () => {
    try {
      downloadBlob(await api.blob("GET", `/invoices/${inv.id}/pdf`), `${inv.invoice_number}.pdf`);
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
  const doVoid = async () => {
    setBusy(true);
    try {
      setInv(await api.post<InvoiceDetail>(`/invoices/${inv.id}/void`, { reason }));
      setVoidOpen(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const errKey = a.last_error_class ? `archive_error.${a.last_error_class}` : null;

  return (
    <>
      <p><Link to="/invoices">← {t("nav.invoices")}</Link></p>
      <div className="page-head">
        <h1>{t("detail.title", { number: inv.invoice_number ?? "" })}</h1>
        <StatusBadge status={inv.status} />
        <span className="spacer" />
        <div className="actions">
          <button className="btn" onClick={download}>{t("detail.download")}</button>
          <button className="btn secondary" onClick={duplicate}>{t("detail.duplicate")}</button>
          {inv.status === "issued" && (
            <button className="btn danger" onClick={() => setVoidOpen(true)}>{t("detail.void")}</button>
          )}
        </div>
      </div>
      {issuedNumber && <div className="alert ok" role="status">{t("issue.done", { number: issuedNumber })}</div>}
      <ErrorAlert error={error} />
      {inv.status === "voided" && (
        <div className="alert warn">{t("detail.voided", { date: dateTime(inv.voided_at), reason: inv.void_reason ?? "" })}</div>
      )}

      <div className="grid grid-2">
        <section className="card">
          <h2>{t("detail.bill_to")}</h2>
          <p style={{ margin: 0 }}>
            <strong>{snap?.bill_to.name}</strong>
            {snap?.bill_to.address_lines.map((l, i) => <span key={i}><br />{l}</span>)}
          </p>
        </section>
        <section className="card">
          <h2>{t("detail.dates")}</h2>
          <dl className="kv">
            <dt>{t("editor.issue_date")}</dt><dd>{ukDate(inv.invoice_date)}</dd>
            <dt>{t("editor.due_date")}</dt><dd>{ukDate(inv.due_date)}</dd>
            <dt>{t("invoices.col_period")}</dt><dd>{period(inv.work_start_date, inv.work_end_date)}</dd>
            {inv.reference && (<><dt>{t("editor.reference")}</dt><dd>{inv.reference}</dd></>)}
          </dl>
        </section>
      </div>

      <section className="card">
        <h2>{t("editor.lines")}</h2>
        <div className="table-wrap">
          <table className="list">
            <thead>
              <tr>
                <th>{t("editor.line_date")}</th>
                <th>{t("editor.line_description")}</th>
                {inv.pension_enabled && <th>{t("editor.line_pensionable")}</th>}
                <th className="money">{t("editor.line_qty")}</th>
                <th className="money">{t("editor.line_rate")}</th>
                <th className="money">{t("editor.line_amount")}</th>
              </tr>
            </thead>
            <tbody>
              {inv.lines.map((l) => (
                <tr key={l.id}>
                  <td>{ukDate(l.service_date)}</td>
                  <td>{l.description} <span className="muted">({t(`unit.${l.unit}` as MessageKey)})</span></td>
                  {inv.pension_enabled && <td>{l.pensionable ? t("common.yes") : t("common.no")}</td>}
                  <td className="money">{l.quantity}</td>
                  <td className="money">{gbp(l.unit_price)}</td>
                  <td className="money">{gbp(l.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totals && (
          <dl className="kv" style={{ marginTop: "1rem", marginLeft: "auto", maxWidth: 460 }}>
            <dt>{t("totals.subtotal")}</dt><dd className="money">{gbp(totals.fee_subtotal)}</dd>
            {totals.employer_rate && totals.pensionable_basic_total !== "0.00" && (
              <>
                <dt>{t("totals.basic")}</dt><dd className="money">{gbp(totals.pensionable_basic_total)}</dd>
                <dt>{t("totals.pensionable_pay", { fraction: pct(totals.pensionable_fraction) })}</dt>
                <dd className="money muted">{gbp(totals.pensionable_pay)}</dd>
                <dt>{t("totals.employer", { rate: pct(totals.employer_rate) })}</dt>
                <dd className="money">{gbp(totals.employer_contribution)}</dd>
              </>
            )}
            <dt><strong>{t("totals.total")}</strong></dt><dd className="money"><strong>{gbp(totals.grand_total)}</strong></dd>
          </dl>
        )}
        <p className="hint">{t("detail.immutable")}</p>
      </section>

      <section className="card" aria-labelledby="h-archive">
        <h2 id="h-archive">{t("detail.archive")}</h2>
        <p style={{ marginTop: 0 }} aria-live="polite">
          <span className="badge synced"><span aria-hidden="true">✓</span> {t("archive.local_saved")}</span>{" "}
          <ArchiveBadge archive={a} />
          {a.status === "not_configured" && !a.webdav_enabled && <span className="muted"> {t("archive.disabled")}</span>}
        </p>
        {a.webdav_enabled && a.status !== "not_configured" && (
          <dl className="kv">
            {a.remote_path && (<><dt>{t("archive.remote_path")}</dt><dd className="mono">{decodeURIComponent(a.remote_path)}</dd></>)}
            {a.last_attempt_at && (<><dt>{t("archive.last_attempt_label")}</dt><dd>{dateTime(a.last_attempt_at)}</dd></>)}
          </dl>
        )}
        {a.status === "synced" && a.verified_sha256 && <p className="hint">✓ {t("archive.verified")}</p>}
        {(a.status === "failed" || a.status === "conflict") && a.webdav_enabled && (
          <div className="alert error" style={{ marginTop: "0.75rem" }}>
            {a.status === "conflict" ? t("archive.conflict_help") : errKey && hasKey(errKey) ? t(errKey as MessageKey) : a.last_error_class}
            {a.retry_paused && a.status === "failed" && <div>{t("archive.paused")}</div>}
            {!a.retry_paused && a.next_retry_at && <div>{t("archive.next_retry", { when: dateTime(a.next_retry_at) })}</div>}
          </div>
        )}
        {a.webdav_enabled && (
          <div className="actions" style={{ marginTop: "0.5rem" }}>
            <button className="btn secondary" onClick={retry} disabled={busy || a.status === "uploading"}>
              {a.status === "not_configured" ? t("archive.upload_now") : a.status === "synced" ? t("archive.reverify") : t("archive.retry")}
            </button>
          </div>
        )}
        <p className="hint mono" style={{ marginTop: "0.75rem" }}>{t("detail.checksum")}: {inv.local_pdf_sha256}</p>
      </section>

      <section className="card">
        <h2>{t("detail.history")}</h2>
        <ul className="timeline">
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
      </section>

      <Dialog
        open={voidOpen}
        title={t("detail.void_title")}
        onClose={() => setVoidOpen(false)}
        footer={
          <>
            <button className="btn secondary" onClick={() => setVoidOpen(false)}>{t("common.cancel")}</button>
            <button className="btn danger" onClick={doVoid} disabled={busy || !reason.trim()}>{t("detail.void")}</button>
          </>
        }
      >
        <p>{t("detail.void_body")}</p>
        <Field id="void-reason" label={t("detail.void_reason")}>
          <textarea id="void-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} autoFocus />
        </Field>
      </Dialog>
    </>
  );
}
