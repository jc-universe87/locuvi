import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArchiveBadge, ErrorAlert, StatusBadge } from "../components/ui";
import { useT } from "../i18n";
import { api, downloadBlob } from "../lib/api";
import { gbp, period, ukDate } from "../lib/format";
import type { InvoiceDetail, InvoiceSummary } from "../lib/types";

interface PageData {
  items: InvoiceSummary[];
  total: number;
  page: number;
  page_size: number;
}

export function invoiceHref(inv: InvoiceSummary) {
  return inv.status === "draft" ? `/invoices/${inv.id}/edit` : `/invoices/${inv.id}`;
}

export default function InvoicesPage() {
  const { t } = useT();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (q.trim()) params.set("q", q.trim());
    if (status) params.set("status", status);
    try {
      setData(await api.get<PageData>(`/invoices?${params}`));
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [q, status, page]);

  useEffect(() => {
    const id = setTimeout(load, 200);
    return () => clearTimeout(id);
  }, [load]);

  const download = async (inv: InvoiceSummary) => {
    try {
      downloadBlob(await api.blob("GET", `/invoices/${inv.id}/pdf`), `${inv.invoice_number}.pdf`);
    } catch (e) {
      setError(e);
    }
  };
  const duplicate = async (inv: InvoiceSummary) => {
    try {
      const d = await api.post<InvoiceDetail>(`/invoices/${inv.id}/duplicate`);
      nav(`/invoices/${d.id}/edit`);
    } catch (e) {
      setError(e);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <div className="page-head">
        <h1>{t("invoices.title")}</h1>
        <span className="spacer" />
        <Link className="btn" to="/invoices/new">
          + {t("invoices.new")}
        </Link>
      </div>
      <div className="card">
        <div className="grid grid-2" style={{ marginBottom: "0.75rem" }}>
          <div className="field">
            <label htmlFor="q">{t("common.search")}</label>
            <input id="q" type="search" value={q} placeholder={t("invoices.search_placeholder")}
              onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <div className="field">
            <label htmlFor="status">{t("invoices.filter_status")}</label>
            <select id="status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">{t("invoices.filter_all")}</option>
              <option value="draft">{t("status.draft")}</option>
              <option value="issued">{t("status.issued")}</option>
              <option value="voided">{t("status.voided")}</option>
            </select>
          </div>
        </div>
        <ErrorAlert error={error} />
        {data && data.items.length === 0 && (
          <p className="muted">{q || status ? t("invoices.none_match") : t("invoices.empty")}</p>
        )}
        {data && data.items.length > 0 && (
          <>
            <div className="table-wrap responsive">
              <table className="list">
                <thead>
                  <tr>
                    <th>{t("invoices.col_number")}</th>
                    <th>{t("invoices.col_practice")}</th>
                    <th>{t("invoices.col_issued")}</th>
                    <th>{t("invoices.col_period")}</th>
                    <th className="money">{t("invoices.col_total")}</th>
                    <th>{t("invoices.col_status")}</th>
                    <th>{t("invoices.col_archive")}</th>
                    <th><span className="sr-only">{t("invoices.open")}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((inv) => (
                    <tr key={inv.id} className="clickable" onClick={() => nav(invoiceHref(inv))}>
                      <td>
                        <Link to={invoiceHref(inv)} onClick={(e) => e.stopPropagation()}>
                          {inv.invoice_number ?? t("status.draft")}
                        </Link>
                      </td>
                      <td>{inv.practice_name ?? t("common.none")}</td>
                      <td>{inv.status === "draft" ? t("common.none") : ukDate(inv.invoice_date)}</td>
                      <td>{period(inv.work_start_date, inv.work_end_date)}</td>
                      <td className="money">{gbp(inv.grand_total)}</td>
                      <td><StatusBadge status={inv.status} /></td>
                      <td>{inv.status !== "draft" && <ArchiveBadge archive={inv.archive} compact />}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="actions" style={{ flexWrap: "nowrap" }}>
                          {inv.status !== "draft" && (
                            <button className="btn ghost small" onClick={() => download(inv)}>
                              {t("invoices.download")}
                            </button>
                          )}
                          <button className="btn ghost small" onClick={() => duplicate(inv)}>
                            {t("invoices.duplicate")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="cards">
              {data.items.map((inv) => (
                <Link key={inv.id} to={invoiceHref(inv)} className="item-card">
                  <div className="row">
                    <span className="num">{inv.invoice_number ?? t("status.draft")}</span>
                    <span className="money">{gbp(inv.grand_total)}</span>
                  </div>
                  <div className="row">
                    <span>{inv.practice_name ?? t("common.none")}</span>
                    <StatusBadge status={inv.status} />
                  </div>
                  <div className="row muted">
                    <span>{period(inv.work_start_date, inv.work_end_date)}</span>
                    {inv.status !== "draft" && <ArchiveBadge archive={inv.archive} compact />}
                  </div>
                </Link>
              ))}
            </div>
            {pages > 1 && (
              <div className="actions" style={{ justifyContent: "center", marginTop: "1rem" }}>
                <button className="btn secondary small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  {t("common.previous")}
                </button>
                <span className="muted">{t("common.page_of", { page, pages })}</span>
                <button className="btn secondary small" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  {t("common.next")}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
