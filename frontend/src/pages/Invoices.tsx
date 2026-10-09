import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArchivePill, ErrorAlert, Icon, InvoicePill, PageHead, Segmented } from "../components/ui";
import { useT } from "../i18n";
import { api } from "../lib/api";
import { gbp, period } from "../lib/format";
import type { InvoiceSummary } from "../lib/types";

interface PageData {
  items: InvoiceSummary[];
  total: number;
  page: number;
  page_size: number;
}

type Filter = "all" | "draft" | "unpaid" | "paid";

export function invoiceHref(inv: InvoiceSummary) {
  return inv.status === "draft" ? `/invoices/${inv.id}/edit` : `/invoices/${inv.id}`;
}

export default function InvoicesPage() {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: "30" });
    if (q.trim()) params.set("q", q.trim());
    if (filter === "draft") params.set("status", "draft");
    if (filter === "unpaid") params.set("payment", "unpaid,part_paid,overdue");
    if (filter === "paid") params.set("payment", "paid");
    try {
      setData(await api.get<PageData>(`/invoices?${params}`));
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [q, filter, page]);

  useEffect(() => {
    const id = setTimeout(load, 150);
    return () => clearTimeout(id);
  }, [load]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <PageHead title={t("invoices.title")}>
        <Link className="btn secondary small" to="/bank">
          <Icon name="money" size={16} /> {t("bank.title")}
        </Link>
        <Link className="btn secondary small" to="/invoices/new">
          <Icon name="plus" size={16} /> {t("invoices.new")}
        </Link>
      </PageHead>
      <div className="row wrap" style={{ marginBottom: "0.9rem" }}>
        <Segmented<Filter>
          value={filter}
          onChange={(f) => {
            setFilter(f);
            setPage(1);
          }}
          label={t("invoices.filter_status")}
          options={[
            { value: "all", label: t("invoices.filter_all") },
            { value: "draft", label: t("invoices.filter_drafts") },
            { value: "unpaid", label: t("invoices.filter_unpaid") },
            { value: "paid", label: t("invoices.filter_paid") },
          ]}
        />
        <span className="spacer" />
        <label className="sr-only" htmlFor="q">{t("common.search")}</label>
        <input id="q" type="search" value={q} placeholder={t("invoices.search_placeholder")}
          style={{ maxWidth: "18rem", background: "var(--card)" }}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }} />
      </div>
      <ErrorAlert error={error} />
      {data && data.items.length === 0 && (
        <div className="card empty">
          <div className="big" aria-hidden="true">🧾</div>
          <p>{q || filter !== "all" ? t("invoices.none_match") : t("invoices.empty")}</p>
          {!q && filter === "all" && <Link to="/diary" className="btn">{t("invoices.start_in_diary")}</Link>}
        </div>
      )}
      {data && data.items.length > 0 && (
        <div className="card flush">
          {data.items.map((inv) => (
            <Link key={inv.id} to={invoiceHref(inv)} className="list-row">
              <span className="list-main">
                <span className="list-title">
                  {inv.practice_name ?? t("today.no_practice")}
                </span>
                <span className="list-sub">
                  {inv.invoice_number ?? t("status.draft")} · {period(inv.work_start_date, inv.work_end_date)}
                </span>
              </span>
              <span style={{ display: "grid", justifyItems: "end", gap: "0.25rem" }}>
                <span className="money" style={{ fontWeight: 600 }}>{gbp(inv.grand_total)}</span>
                <span className="row" style={{ gap: "0.3rem" }}>
                  {inv.status !== "draft" && <ArchivePill archive={inv.archive} />}
                  <InvoicePill status={inv.status} payment={inv.payment} due={inv.due_date} />
                </span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </Link>
          ))}
        </div>
      )}
      {pages > 1 && (
        <div className="actions" style={{ justifyContent: "center" }}>
          <button className="btn secondary small" disabled={page <= 1} onClick={() => setPage(page - 1)}>{t("common.previous")}</button>
          <span className="muted">{t("common.page_of", { page, pages })}</span>
          <button className="btn secondary small" disabled={page >= pages} onClick={() => setPage(page + 1)}>{t("common.next")}</button>
        </div>
      )}
    </>
  );
}
