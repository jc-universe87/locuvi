import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorAlert, Icon, useToast } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { gbp, gbpRound, monthLabel, period, weekdayDate } from "../lib/format";
import type { InvoiceDetail, Overview } from "../lib/types";

function greetingKey(): MessageKey {
  const h = new Date().getHours();
  return h < 12 ? "today.morning" : h < 18 ? "today.afternoon" : "today.evening";
}

function firstName(full: string): string {
  const parts = full.replace(/^(dr|mr|mrs|ms|miss|prof)\.?\s+/i, "").trim().split(/\s+/);
  return parts[0] ?? "";
}

export default function TodayPage() {
  const { t, tn } = useT();
  const nav = useNavigate();
  const toast = useToast();
  const [ov, setOv] = useState<Overview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setOv(await api.get<Overview>("/overview"));
    } catch (e) {
      setError(e);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!ov || ov.setup.completed) return;
    let skipped = false;
    try {
      skipped = sessionStorage.getItem("locuvi.setup.skip") === "1";
    } catch {
      /* ignore */
    }
    if (!skipped) nav("/welcome", { replace: true });
  }, [ov, nav]);

  if (error && !ov) return <ErrorAlert error={error} />;
  if (!ov) return null;

  const createInvoice = async (practice_id: string, month: string) => {
    setBusy(`${practice_id}${month}`);
    try {
      const d = await api.post<InvoiceDetail>("/sessions/invoice", { practice_id, month });
      nav(`/invoices/${d.id}/edit`);
    } catch (e) {
      setError(e);
      setBusy(null);
    }
  };

  const markPaid = async (id: string, number: string) => {
    try {
      const d = await api.post<InvoiceDetail>(`/invoices/${id}/payments`, {});
      const pid = d.payments[d.payments.length - 1]?.id;
      toast({
        text: t("pay.marked_paid", { number }),
        undo: pid
          ? async () => {
              await api.del(`/payments/${pid}`);
              void load();
            }
          : undefined,
      });
      void load();
    } catch (e) {
      setError(e);
    }
  };

  const name = firstName(ov.greeting_name);
  const tasks =
    ov.ready_to_invoice.length + ov.drafts.length + ov.unpaid.length + ov.pension_due.length;

  return (
    <>
      <p className="hero-date">{weekdayDate(ov.today)}</p>
      <h1>{name ? t(greetingKey(), { name }) : t("today.hello")}</h1>
      <ErrorAlert error={error} />

      {!ov.setup.completed && (
        <Link to="/welcome" className="card list-row" style={{ textDecoration: "none" }}>
          <span className="task-icon"><Icon name="settings" /></span>
          <span className="list-main">
            <span className="list-title">{t("today.finish_setup")}</span>
            <span className="list-sub">{t("today.finish_setup_sub")}</span>
          </span>
          <span className="chev"><Icon name="chevron" size={18} /></span>
        </Link>
      )}

      <div className="stats">
        <div className="stat">
          <div className="k">{t("today.stat_month")}</div>
          <div className="v">{gbpRound(ov.this_month_invoiced)}</div>
        </div>
        <div className="stat">
          <div className="k">{t("today.stat_outstanding")}</div>
          <div className="v">{gbpRound(ov.outstanding_total)}</div>
        </div>
        <div className="stat">
          <div className="k">{t("today.stat_tax_year")}</div>
          <div className="v">{gbpRound(ov.tax_year.invoiced)}</div>
        </div>
      </div>

      {tasks === 0 ? (
        <div className="card caught-up">
          <span className="tick"><Icon name="check" size={28} /></span>
          <h2 style={{ margin: "0.25rem 0" }}>{t("today.caught_up")}</h2>
          <p className="muted" style={{ margin: 0 }}>{t("today.caught_up_sub")}</p>
        </div>
      ) : (
        <section className="card flush" aria-labelledby="h-todo">
          <h2 id="h-todo" className="sr-only">{t("today.todo")}</h2>
          {ov.ready_to_invoice.map((g) => (
            <div key={g.practice_id + g.month} className="task">
              <span className="task-icon"><Icon name="invoices" /></span>
              <span className="list-main">
                <span className="list-title">{t("today.ready_title", { month: monthLabel(g.month) })}</span>
                <span className="list-sub">
                  {g.practice_name} · {tn("today.sessions", g.sessions)} · {gbp(g.total)}
                </span>
              </span>
              <button className="btn small" disabled={busy !== null} onClick={() => createInvoice(g.practice_id, g.month)}>
                {t("today.create_invoice")}
              </button>
            </div>
          ))}
          {ov.drafts.map((d) => (
            <Link key={d.id} to={`/invoices/${d.id}/edit`} className="task" style={{ textDecoration: "none", color: "inherit" }}>
              <span className="task-icon"><Icon name="invoices" /></span>
              <span className="list-main">
                <span className="list-title">{t("today.draft_title", { practice: d.practice_name ?? t("today.no_practice") })}</span>
                <span className="list-sub">{period(d.work_start_date, d.work_end_date)} · {gbp(d.grand_total)}</span>
              </span>
              <span className="btn small secondary">{t("today.review")}</span>
            </Link>
          ))}
          {ov.unpaid.map((u) => (
            <div key={u.id} className="task">
              <span className={`task-icon ${u.state === "overdue" ? "warn" : ""}`}><Icon name="money" /></span>
              <Link to={`/invoices/${u.id}`} className="list-main" style={{ textDecoration: "none", color: "inherit" }}>
                <span className="list-title">
                  {u.state === "overdue"
                    ? tn("today.overdue_title", u.days_overdue, { number: u.invoice_number })
                    : t("today.awaiting_title", { number: u.invoice_number })}
                </span>
                <span className="list-sub">{u.practice_name} · {gbp(u.outstanding)}</span>
              </Link>
              <button className="btn small secondary" onClick={() => markPaid(u.id, u.invoice_number)}>
                {t("pay.mark_paid")}
              </button>
            </div>
          ))}
          {ov.pension_due.map((p) => (
            <Link key={p.month} to="/pension" className="task" style={{ textDecoration: "none", color: "inherit" }}>
              <span className="task-icon ok"><Icon name="pension" /></span>
              <span className="list-main">
                <span className="list-title">{t("today.pension_title", { month: monthLabel(p.month) })}</span>
                <span className="list-sub">{t("today.pension_sub", { pay: gbp(p.pensionable_pay) })}</span>
              </span>
              <span className="chev"><Icon name="chevron" size={18} /></span>
            </Link>
          ))}
        </section>
      )}

      <section className="card flush" aria-labelledby="h-upcoming">
        <div className="row" style={{ padding: "0.9rem 1.15rem 0.25rem" }}>
          <h2 id="h-upcoming" style={{ margin: 0 }}>{t("today.coming_up")}</h2>
          <span className="spacer" />
          <Link to="/diary" className="btn ghost small">{t("today.open_diary")}</Link>
        </div>
        {ov.upcoming.length === 0 ? (
          <p className="muted" style={{ padding: "0.25rem 1.15rem 1rem", margin: 0 }}>{t("today.nothing_booked")}</p>
        ) : (
          <ul className="list">
            {ov.upcoming.map((u) => (
              <li key={u.id}>
                <span className="list-main">
                  <span className="list-title">{u.practice_name}</span>
                  <span className="list-sub">{weekdayDate(u.date)} · {t(`unit.${u.unit}` as MessageKey)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link to="/diary" className="fab" aria-label={t("today.log_session")} title={t("today.log_session")}>
        <Icon name="plus" size={26} />
      </Link>
    </>
  );
}
