import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Dialog, ErrorAlert, Icon, PageHead, Segmented, useConfirm, useToast } from "../components/ui";
import { restoreFromBin } from "../lib/trash";
import { useT } from "../i18n";
import { api, downloadBlob } from "../lib/api";
import { dayMonth, gbp, monthLabel, pct, ukDate } from "../lib/format";
import type { PensionMonth } from "../lib/types";

interface FormBItem {
  invoice_id: string;
  invoice_number: string;
  practice: string;
  work_month: string;
  paid_on: string;
  amount: string;
  pensionable_pay: string;
  employer: string;
}
interface FormA {
  key: string;
  deadline: string;
  received_pay: string;
  form_a: { status: "to_send" | "sent" | "signed"; sent_on: string | null; signed_on: string | null };
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
  form_b: {
    items: FormBItem[];
    pensionable_pay: string; employer: string; employee_rate: string | null; employee: string | null;
    total_payable: string | null; due_by: string;
  };
  pcse: {
    status: "none" | "match" | "mismatch";
    expected_pay: string;
    expected_contributions: string | null;
    recorded_pay: string | null;
    recorded_contributions: string | null;
    difference: string | null;
  };
}

export default function PensionPage() {
  const { t, tn } = useT();
  const toast = useToast();
  const confirm = useConfirm();
  const [data, setData] = useState<{ months: PensionMonth[]; employee_rate: string | null } | null>(null);
  const [open, setOpen] = useState<MonthFigures | null>(null);
  const [error, setError] = useState<unknown>(null);
  const pcseFile = useRef<HTMLInputElement>(null);

  const formA = async (month: string, key: string, status: FormA["form_a"]["status"]) => {
    try {
      setOpen(await api.post<MonthFigures>(`/pension/${month}/form-a`, { practice_key: key, status }));
      await load();
    } catch (e) {
      setError(e);
    }
  };
  const savePcse = async (month: string, pay: string, contributions: string) => {
    try {
      setOpen(await api.put<MonthFigures>(`/pension/${month}/pcse`, {
        pensionable_pay: pay.trim() || null, contributions: contributions.trim() || null,
      }));
      await load();
    } catch (e) {
      setError(e);
    }
  };
  const importPcse = async (f: File) => {
    try {
      const form = new FormData();
      form.append("file", f, f.name);
      const r = await api.upload<{ imported: number }>("/pension/pcse/import", form);
      toast({ text: tn("pension.pcse_imported", r.imported) });
      await load();
    } catch (e) {
      setError(e);
    }
  };

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
  const submitted = async (month: string, on: boolean, ask = true) => {
    if (!on && ask) {
      const ok = await confirm({
        title: t("trash.ask_unmark", { month: monthLabel(month) }),
        body: t("trash.ask_unmark_body"),
        confirm: t("pension.unmark"),
      });
      if (!ok) return;
    }
    try {
      const r: { months: PensionMonth[]; trash_id?: string | null } = on ? await api.post<{ months: PensionMonth[] }>(`/pension/${month}/submitted`, {})
        : await api.del<{ months: PensionMonth[]; trash_id: string | null }>(`/pension/${month}/submitted`);
      setData((d) => (d ? { ...d, months: r.months } : d));
      // Undo of a mark needs no question; an unmark can be undone from the bin.
      if (on) toast({ text: t("pension.marked", { month: monthLabel(month) }), undo: () => void submitted(month, false, false) });
      else if (ask && r.trash_id) {
        const tid = r.trash_id;
        toast({
          text: t("trash.unmarked", { month: monthLabel(month) }),
          undo: () => void restoreFromBin(tid, t, tn, toast).then(() => api.get<{ months: PensionMonth[] }>("/pension"))
            .then((x) => setData((d) => (d ? { ...d, months: x.months } : d)), () => undefined),
        });
      }
      setOpen(null);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <>
      <PageHead title={t("pension.title")}>
        <button className="btn secondary small" onClick={() => pcseFile.current?.click()}>
          <Icon name="upload" size={16} /> {t("pension.pcse_import")}
        </button>
      </PageHead>
      <input ref={pcseFile} type="file" accept=".csv,text/csv" hidden aria-label={t("pension.pcse_import")}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void importPcse(f); e.target.value = ""; }} />
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
                  {m.practices > 0 && tn("pension.row_work", m.practices, { pay: gbp(m.work_pay), signed: m.forms_a_signed })}
                  {m.practices > 0 && m.received_items > 0 && " · "}
                  {m.received_items > 0 && t("pension.row_received", { pay: gbp(m.pensionable_pay), due: ukDate(m.due_by) })}
                </span>
              </span>
              {m.pcse === "mismatch" && <span className="pill overdue">{t("pension.pcse_mismatch")}</span>}
              {m.pcse === "match" && <span className="pill ok">{t("pension.pcse_match")}</span>}
              {m.submitted_on ? (
                m.changed_since_submitted
                  ? <span className="pill warn">{t("pension.changed")}</span>
                  : <span className="pill ok">✓ {t("pension.submitted")}</span>
              ) : m.ready ? (
                <span className="pill due">{t("pension.ready")}</span>
              ) : m.received_items > 0 ? (
                <span className="pill draft">{t("pension.in_progress")}</span>
              ) : null}
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
                  <button className="btn" disabled={open.form_b.items.length === 0} onClick={() => submitted(open.month, true)}><Icon name="check" size={18} /> {t("pension.mark")}</button>
                )}
              </>
            );
          })()}>
          {open.forms_a.map((a, i) => (
            <div key={i} style={{ marginBottom: "1rem" }}>
              <h3 style={{ marginTop: i ? "0.5rem" : 0 }}>{t("pension.form_a", { n: i + 1 })} · {a.practice_name} · {a.invoices.join(", ")}</h3>
              <div className="row wrap" style={{ gap: "0.5rem", margin: "0.25rem 0 0.5rem" }}>
                <Segmented<FormA["form_a"]["status"]> value={a.form_a.status} label={t("pension.form_a_status")}
                  onChange={(v) => void formA(open.month, a.key, v)}
                  options={[
                    { value: "to_send", label: t("pension.fa_to_send") },
                    { value: "sent", label: t("pension.fa_sent") },
                    { value: "signed", label: t("pension.fa_signed") },
                  ]} />
                <span className="hint">
                  {a.form_a.signed_on ? t("pension.fa_signed_on", { date: ukDate(a.form_a.signed_on) })
                    : a.form_a.sent_on ? t("pension.fa_sent_on", { date: ukDate(a.form_a.sent_on) }) : ""}
                </span>
              </div>
              <dl className="kv">
                <dt>{t("pension.sessions")}</dt><dd>{a.session_dates.map((d) => dayMonth(d)).join(", ")}</dd>
                <dt>{t("pension.fees")}</dt><dd className="money">{gbp(a.fees)}</dd>
                <dt>{t("pension.pay")}</dt><dd className="money">{gbp(a.pensionable_pay)}</dd>
                <dt>{t("pension.employer")}</dt><dd className="money">{gbp(a.employer)}</dd>
                <dt>{t("pension.ten_week")}</dt><dd>{ukDate(a.deadline)}</dd>
              </dl>
            </div>
          ))}
          {open.forms_a.length === 0 && <p className="muted">{t("pension.no_work_month")}</p>}
          <h3>{t("pension.form_b")}</h3>
          <p className="hint" style={{ marginTop: 0 }}>{t("pension.form_b_explain", { due: ukDate(open.form_b.due_by) })}</p>
          {open.form_b.items.length === 0 ? (
            <p className="muted">{t("pension.nothing_received")}</p>
          ) : (
            <ul className="list" style={{ marginBottom: "0.5rem" }}>
              {open.form_b.items.map((r, j) => (
                <li key={j} style={{ padding: "0.5rem 0" }}>
                  <span className="list-main">
                    <span className="list-title">{r.invoice_number} · {r.practice}</span>
                    <span className="list-sub">{t("pension.item_sub", { work: monthLabel(r.work_month), paid: ukDate(r.paid_on), amount: gbp(r.amount) })}</span>
                  </span>
                  <span className="money">{gbp(r.pensionable_pay)}</span>
                </li>
              ))}
            </ul>
          )}
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
          <PcseBox key={open.month} fig={open} onSave={(pay, c) => void savePcse(open.month, pay, c)} />
        </Dialog>
      )}
    </>
  );
}

function PcseBox({ fig, onSave }: { fig: MonthFigures; onSave: (pay: string, contributions: string) => void }) {
  const { t } = useT();
  const p = fig.pcse;
  const [pay, setPay] = useState(p.recorded_pay ?? "");
  const [contrib, setContrib] = useState(p.recorded_contributions ?? "");
  return (
    <>
      <h3>{t("pension.pcse_title")}</h3>
      <p className="hint" style={{ marginTop: 0 }}>{t("pension.pcse_hint")}</p>
      {p.status === "match" && <div className="alert ok">✓ {t("pension.pcse_match_long")}</div>}
      {p.status === "mismatch" && (
        <div className="alert warn">{t("pension.pcse_mismatch_long", { diff: gbp(p.difference) })}</div>
      )}
      <div className="row wrap" style={{ gap: "0.5rem", alignItems: "flex-end" }}>
        <label className="field" style={{ flex: "1 1 9rem", margin: 0 }}>
          <span className="label">{t("pension.pcse_pay", { expected: gbp(p.expected_pay) })}</span>
          <input type="text" inputMode="decimal" value={pay} placeholder="0.00" onChange={(e) => setPay(e.target.value)} />
        </label>
        <label className="field" style={{ flex: "1 1 9rem", margin: 0 }}>
          <span className="label">{t("pension.pcse_contrib", { expected: gbp(p.expected_contributions) })}</span>
          <input type="text" inputMode="decimal" value={contrib} placeholder="0.00" onChange={(e) => setContrib(e.target.value)} />
        </label>
        <button className="btn secondary small" onClick={() => onSave(pay, contrib)}>{t("common.save")}</button>
      </div>
    </>
  );
}
