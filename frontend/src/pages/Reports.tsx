import { useEffect, useState } from "react";
import { ErrorAlert, Icon, PageHead, Segmented } from "../components/ui";
import { useT } from "../i18n";
import { api, downloadBlob } from "../lib/api";
import { gbp, gbpRound, monthLabel, monthShort } from "../lib/format";

type Basis = "cash" | "accruals";

interface Summary {
  basis: Basis;
  self_assessment: {
    fees: string;
    employer_contributions: string;
    pensionable_pay: string;
    employee_rate: string | null;
    employee_contributions_estimate: string | null;
  };
  tax_year: number;
  label: string;
  available_years: number[];
  invoice_count: number;
  totals: { income: string; invoiced: string; fees: string; employer: string; paid: string; outstanding: string; credited: string };
  months: { month: string; total: string }[];
  practices: { practice: string; invoices: number; total: string }[];
}

export default function ReportsPage() {
  const { t, tn } = useT();
  const [year, setYear] = useState<number | null>(null);
  const [basis, setBasis] = useState<Basis | null>(null);
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const q = new URLSearchParams();
    if (year) q.set("tax_year", String(year));
    if (basis) q.set("basis", basis);
    api.get<Summary>(`/reports/summary?${q}`).then(setS, setError);
  }, [year, basis]);
  const chooseBasis = (b: Basis) => {
    setBasis(b);
    void api.patch("/settings/profile", { accounting_basis: b }).catch(() => undefined); // remembered
  };

  if (error && !s) return <ErrorAlert error={error} />;
  if (!s) return null;
  const max = Math.max(1, ...s.months.map((m) => Number(m.total)));

  const dl = async (path: string, name: string) => {
    try {
      downloadBlob(await api.blob("GET", path), name);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <>
      <PageHead title={t("reports.title")}>
        {s.available_years.length > 1 && (
          <select aria-label={t("reports.tax_year")} value={s.tax_year} onChange={(e) => setYear(Number(e.target.value))}
            style={{ width: "auto", background: "var(--card)" }}>
            {s.available_years.map((y) => <option key={y} value={y}>{`${y}/${String(y + 1).slice(-2)}`}</option>)}
          </select>
        )}
      </PageHead>
      <div className="row wrap" style={{ marginBottom: "0.5rem" }}>
        <Segmented<Basis> value={s.basis} onChange={chooseBasis} label={t("reports.basis")} options={[
          { value: "cash", label: t("reports.basis_cash") },
          { value: "accruals", label: t("reports.basis_accruals") },
        ]} />
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        {t(s.basis === "cash" ? "reports.lead_cash" : "reports.lead_accruals", { year: s.label })}
      </p>
      <ErrorAlert error={error} />

      <div className="stats">
        <div className="stat"><div className="k">{t("reports.invoiced")}</div><div className="v">{gbpRound(s.totals.invoiced)}</div></div>
        <div className="stat"><div className="k">{t("reports.received")}</div><div className="v">{gbpRound(s.totals.paid)}</div></div>
        <div className="stat"><div className="k">{t("reports.outstanding")}</div><div className="v">{gbpRound(s.totals.outstanding)}</div></div>
        <div className="stat"><div className="k">{t("reports.employer")}</div><div className="v">{gbpRound(s.totals.employer)}</div></div>
      </div>

      <section className="card" aria-labelledby="h-chart">
        <h2 id="h-chart">{s.basis === "cash" ? t("reports.by_month_cash") : t("reports.by_month")}</h2>
        <div className="bars" role="list">
          {s.months.map((m) => {
            const v = Number(m.total);
            const label = `${monthLabel(m.month)}: ${gbp(m.total)}`;
            return (
              <div key={m.month} className="bar-col" role="listitem" tabIndex={0} aria-label={label}>
                <span className="tip">{label}</span>
                <span className="bar" style={{ height: `${(v / max) * 100}%` }} />
              </div>
            );
          })}
        </div>
        <div className="bar-labels" aria-hidden="true">
          {s.months.map((m) => <span key={m.month}>{monthShort(m.month).slice(0, 1)}</span>)}
        </div>
        <details className="more" style={{ marginTop: "0.75rem" }}>
          <summary>{t("reports.show_table")}</summary>
          <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "0.5rem", fontSize: "0.9rem" }}>
            <tbody>
              {s.months.map((m) => (
                <tr key={m.month} style={{ borderTop: "1px solid var(--line)" }}>
                  <td style={{ padding: "0.3rem 0" }}>{monthLabel(m.month)}</td>
                  <td className="money right">{gbp(m.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      {s.practices.length > 0 && (
        <section className="card flush" aria-labelledby="h-pr">
          <h2 id="h-pr" style={{ padding: "0.9rem 1.15rem 0", margin: 0 }}>{t("reports.by_practice")}</h2>
          <ul className="list">
            {s.practices.map((p) => (
              <li key={p.practice}>
                <span className="list-main">
                  <span className="list-title">{p.practice}</span>
                  <span className="list-sub">{s.basis === "cash" ? tn("reports.payment_count", p.invoices) : tn("reports.invoice_count", p.invoices)}</span>
                </span>
                <span className="money">{gbp(p.total)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card" aria-labelledby="h-sa">
        <h2 id="h-sa">{t("reports.sa_title")} · {s.basis === "cash" ? t("reports.basis_cash") : t("reports.basis_accruals")}</h2>
        <dl className="kv">
          <dt>{t("reports.sa_fees")}</dt><dd className="money">{gbp(s.self_assessment.fees)}</dd>
          <dt>{t("reports.sa_employer")}</dt><dd className="money">{gbp(s.self_assessment.employer_contributions)}</dd>
          <dt>{t("reports.sa_pay")}</dt><dd className="money">{gbp(s.self_assessment.pensionable_pay)}</dd>
          <dt>{t("reports.sa_employee")}</dt>
          <dd className="money">{s.self_assessment.employee_contributions_estimate ? gbp(s.self_assessment.employee_contributions_estimate) : t("common.none")}</dd>
        </dl>
        <p className="hint" style={{ marginBottom: 0 }}>{s.basis === "cash" ? t("reports.sa_note_cash") : t("reports.sa_note")}</p>
      </section>

      <section className="card">
        <h2>{t("reports.export")}</h2>
        <p className="muted" style={{ marginTop: 0 }}>{t("reports.export_lead")}</p>
        <div className="actions">
          <button className="btn secondary" onClick={() => dl(`/reports/invoices.csv?tax_year=${s.tax_year}`, `locuvi-invoices-${s.tax_year}-${s.tax_year + 1}.csv`)}>
            <Icon name="download" size={18} /> {t("reports.csv")}
          </button>
          <button className="btn secondary" onClick={() => dl(`/reports/receipts.csv?tax_year=${s.tax_year}`, `locuvi-receipts-${s.tax_year}.csv`)}>
            <Icon name="download" size={18} /> {t("reports.receipts_csv")}
          </button>
          <button className="btn secondary" onClick={() => dl(`/reports/year-pack.zip?tax_year=${s.tax_year}`, `locuvi-${s.tax_year}-${s.tax_year + 1}.zip`)}>
            <Icon name="download" size={18} /> {t("reports.pack")}
          </button>
        </div>
      </section>
    </>
  );
}
