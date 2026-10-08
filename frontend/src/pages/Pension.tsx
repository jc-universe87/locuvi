import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Dialog, ErrorAlert, Icon, PageHead, useToast } from "../components/ui";
import { useT } from "../i18n";
import { api, downloadBlob } from "../lib/api";
import { gbp, monthLabel, pct, ukDate } from "../lib/format";
import type { PensionMonth } from "../lib/types";

interface FormA {
  practice_name: string;
  practice_code: string | null;
  session_dates: string[];
  invoices: string[];
  fees: string;
  pensionable_pay: string;
  employer: string;
}
interface MonthFigures {
  month: string;
  forms_a: FormA[];
  form_b: { pensionable_pay: string; employer: string; employee_rate: string | null; employee: string | null; total_payable: string | null };
}

export default function PensionPage() {
  const { t, tn } = useT();
  const toast = useToast();
  const [data, setData] = useState<{ months: PensionMonth[]; employee_rate: string | null } | null>(null);
  const [open, setOpen] = useState<MonthFigures | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get("/pension"));
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const show = async (month: string) => {
    try {
      setOpen(await api.get<MonthFigures>(`/pension/${month}`));
    } catch (e) {
      setError(e);
    }
  };
  const worksheet = async (month: string) => {
    try {
      downloadBlob(await api.blob("GET", `/pension/${month}/worksheet.pdf`), `nhs-pension-worksheet-${month}.pdf`);
    } catch (e) {
      setError(e);
    }
  };
  const submitted = async (month: string, on: boolean) => {
    try {
      const r = on ? await api.post<{ months: PensionMonth[] }>(`/pension/${month}/submitted`, {})
        : await api.del(`/pension/${month}/submitted`).then(() => api.get<{ months: PensionMonth[] }>("/pension"));
      setData((d) => (d ? { ...d, months: r.months } : d));
      if (on) toast({ text: t("pension.marked", { month: monthLabel(month) }), undo: () => void submitted(month, false) });
      setOpen(null);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <>
      <PageHead title={t("pension.title")} />
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("pension.lead")}</p>
      <ErrorAlert error={error} />
      {data && !data.employee_rate && data.months.length > 0 && (
        <div className="alert info">
          {t("pension.set_tier")} <Link to="/settings/pension">{t("pension.set_tier_link")}</Link>
        </div>
      )}
      {data && data.months.length === 0 && (
        <div className="card empty">
          <div className="big" aria-hidden="true">🏛️</div>
          <p>{t("pension.empty")}</p>
        </div>
      )}
      {data && data.months.length > 0 && (
        <div className="card flush">
          {data.months.map((m) => (
            <button key={m.month} type="button" className="list-row" onClick={() => show(m.month)}>
              <span className="list-main">
                <span className="list-title">{monthLabel(m.month)}</span>
                <span className="list-sub">
                  {tn("pension.row_sub", m.practices, { pay: gbp(m.pensionable_pay) })}
                </span>
              </span>
              {m.submitted_on ? (
                m.changed_since_submitted
                  ? <span className="pill warn">{t("pension.changed")}</span>
                  : <span className="pill ok">✓ {t("pension.submitted")}</span>
              ) : m.ready ? (
                <span className="pill due">{t("pension.ready")}</span>
              ) : (
                <span className="pill draft">{t("pension.in_progress")}</span>
              )}
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </button>
          ))}
        </div>
      )}
      <p className="hint">{t("pension.disclaimer")}</p>

      {open && (
        <Dialog open title={monthLabel(open.month)} onClose={() => setOpen(null)}
          footer={(() => {
            const row = data?.months.find((m) => m.month === open.month);
            return (
              <>
                <button className="btn secondary" onClick={() => worksheet(open.month)}><Icon name="download" size={18} /> {t("pension.worksheet")}</button>
                {row?.submitted_on ? (
                  <button className="btn ghost" onClick={() => submitted(open.month, false)}>{t("pension.unmark")}</button>
                ) : (
                  <button className="btn" onClick={() => submitted(open.month, true)}><Icon name="check" size={18} /> {t("pension.mark")}</button>
                )}
              </>
            );
          })()}>
          {open.forms_a.map((a, i) => (
            <div key={i} style={{ marginBottom: "1rem" }}>
              <h3 style={{ marginTop: i ? "0.5rem" : 0 }}>{t("pension.form_a", { n: i + 1 })} · {a.practice_name}</h3>
              <dl className="kv">
                <dt>{t("pension.sessions")}</dt><dd>{a.session_dates.map((d) => ukDate(d).replace(/ \d{4}$/, "")).join(", ")}</dd>
                <dt>{t("pension.fees")}</dt><dd className="money">{gbp(a.fees)}</dd>
                <dt>{t("pension.pay")}</dt><dd className="money">{gbp(a.pensionable_pay)}</dd>
                <dt>{t("pension.employer")}</dt><dd className="money">{gbp(a.employer)}</dd>
              </dl>
            </div>
          ))}
          <h3>{t("pension.form_b")}</h3>
          <dl className="kv">
            <dt>{t("pension.pay")}</dt><dd className="money">{gbp(open.form_b.pensionable_pay)}</dd>
            <dt>{t("pension.employer")}</dt><dd className="money">{gbp(open.form_b.employer)}</dd>
            {open.form_b.employee ? (
              <>
                <dt>{t("pension.employee", { rate: pct(open.form_b.employee_rate) })}</dt><dd className="money">{gbp(open.form_b.employee)}</dd>
                <dt><strong>{t("pension.total")}</strong></dt><dd className="money"><strong>{gbp(open.form_b.total_payable)}</strong></dd>
              </>
            ) : (
              <><dt>{t("pension.employee_short")}</dt><dd><Link to="/settings/pension">{t("pension.set_tier_link")}</Link></dd></>
            )}
          </dl>
        </Dialog>
      )}
    </>
  );
}
