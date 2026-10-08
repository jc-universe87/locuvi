import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Dialog, ErrorAlert, Field, Icon, Segmented, Toggle, useToast } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { addDays, gbp, monthLabel, todayLondon, weekdayDate } from "../lib/format";
import type { InvoiceDetail, Practice, ReadyGroup, Unit, WorkSession } from "../lib/types";

// Fixed categorical order: colour follows the practice, never its rank in a filtered view.
const PRACTICE_COLOURS = ["#294D63", "#8D5968", "#3E7C76", "#8A6420", "#6B5B95", "#56656F"];
const UNITS: Unit[] = ["am", "pm", "day", "hours"];
const DEC = /^\d+(\.\d{1,2})?$/;

function colourFor(practices: Practice[], id: string) {
  const all = [...practices].sort((a, b) => a.id.localeCompare(b.id));
  const i = all.findIndex((p) => p.id === id);
  return PRACTICE_COLOURS[(i < 0 ? 0 : i) % PRACTICE_COLOURS.length];
}

function initials(name: string) {
  const words = name
    .replace(/\b(the|and|of|medical|practice|surgery|health|centre|center|group)\b/gi, "")
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 2);
  return words.slice(0, 2).map((w) => w[0]?.toUpperCase()).join("") || name.slice(0, 2);
}

function monthBounds(ym: string) {
  const [y, m] = ym.split("-").map(Number);
  const start = `${ym}-01`;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { start, end: `${ym}-${String(last).padStart(2, "0")}`, y, m, last };
}

function shiftMonth(ym: string, delta: number) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function remember(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export default function DiaryPage() {
  const { t, tn } = useT();
  const toast = useToast();
  const nav = useNavigate();
  const today = todayLondon();
  const [month, setMonth] = useState(today.slice(0, 7));
  const [practices, setPractices] = useState<Practice[] | null>(null);
  const [practiceId, setPracticeId] = useState<string | null>(remember("locuvi.diary.practice"));
  const [unit, setUnit] = useState<Unit>((remember("locuvi.diary.unit") as Unit) || "am");
  const [rate, setRate] = useState("");
  const [hours, setHours] = useState("4");
  const [editingRate, setEditingRate] = useState(false);
  const [sessions, setSessions] = useState<WorkSession[]>([]);
  const [ready, setReady] = useState<ReadyGroup[]>([]);
  const [open, setOpen] = useState<WorkSession | null>(null);
  const [newPractice, setNewPractice] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const { start, end, y, m, last } = monthBounds(month);

  const load = useCallback(async () => {
    try {
      const [ss, rd] = await Promise.all([
        api.get<WorkSession[]>(`/sessions?start=${start}&end=${end}`),
        api.get<ReadyGroup[]>("/sessions/ready"),
      ]);
      setSessions(ss);
      setReady(rd);
    } catch (e) {
      setError(e);
    }
  }, [start, end]);

  useEffect(() => {
    api.get<Practice[]>("/practices").then((ps) => {
      setPractices(ps);
      setPracticeId((cur) => (cur && ps.some((p) => p.id === cur) ? cur : ps[0]?.id ?? null));
    }, setError);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  // Remembered rate for the chosen practice + session type.
  useEffect(() => {
    if (!practiceId) return;
    remember("locuvi.diary.practice", practiceId);
    remember("locuvi.diary.unit", unit);
    api
      .get<{ rate: string | null }>(`/sessions/suggest-rate?practice_id=${practiceId}&unit=${unit}`)
      .then((r) => {
        setRate(r.rate ?? "");
        setEditingRate(!r.rate);
      }, () => undefined);
  }, [practiceId, unit]);

  const practice = practices?.find((p) => p.id === practiceId) ?? null;
  const byDay = useMemo(() => {
    const map: Record<string, WorkSession[]> = {};
    for (const s of sessions) (map[s.date] ??= []).push(s);
    return map;
  }, [sessions]);

  const tapDay = async (iso: string) => {
    if (!practice) {
      setNewPractice(true);
      return;
    }
    const existing = byDay[iso]?.find((s) => s.practice_id === practice.id && s.unit === unit);
    if (existing) {
      setOpen(existing);
      return;
    }
    if (!DEC.test(rate.trim())) {
      setEditingRate(true);
      return;
    }
    try {
      const [created] = await api.post<WorkSession[]>("/sessions", {
        sessions: [{
          practice_id: practice.id, date: iso, unit,
          rate: rate.trim(),
          ...(unit === "hours" ? { quantity: DEC.test(hours.trim()) ? hours.trim() : "1" } : {}),
        }],
      });
      setSessions((ss) => [...ss, created]);
      setEditingRate(false);
      toast({
        text: t("diary.added", { unit: t(`unit.${unit}` as MessageKey), date: weekdayDate(iso) }),
        undo: async () => {
          await api.del(`/sessions/${created.id}`);
          void load();
        },
      });
      void api.get<ReadyGroup[]>("/sessions/ready").then(setReady, () => undefined);
    } catch (e) {
      setError(e);
    }
  };

  const createInvoice = async (g: ReadyGroup) => {
    try {
      const d = await api.post<InvoiceDetail>("/sessions/invoice", { practice_id: g.practice_id, month: g.month });
      nav(`/invoices/${d.id}/edit`);
    } catch (e) {
      setError(e);
    }
  };

  // Monday-first grid
  const firstDow = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
  const cells: (string | null)[] = [
    ...Array<null>(firstDow).fill(null),
    ...Array.from({ length: last }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`),
  ];
  while (cells.length % 7) cells.push(null);
  const weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

  const monthReady = ready.filter((g) => g.month === month);
  const monthTotal = sessions
    .filter((s) => s.status === "active")
    .reduce((sum, s) => sum + Number(s.rate) * Number(s.quantity), 0);
  const invoicedHere = Array.from(
    new Map(sessions.filter((s) => s.invoice).map((s) => [s.invoice!.id, s.invoice!])).values(),
  );

  if (practices && practices.length === 0) {
    return (
      <>
        <h1>{t("nav.diary")}</h1>
        <div className="card empty">
          <div className="big" aria-hidden="true">🗓️</div>
          <p>{t("diary.no_practices")}</p>
          <button className="btn" onClick={() => setNewPractice(true)}>+ {t("practices.add")}</button>
        </div>
        {newPractice && (
          <PracticeSheet onClose={() => setNewPractice(false)} onSaved={(p) => {
            setPractices([p]);
            setPracticeId(p.id);
            setNewPractice(false);
          }} />
        )}
      </>
    );
  }

  return (
    <>
      <h1>{t("nav.diary")}</h1>
      <ErrorAlert error={error} />

      <div className="card" style={{ paddingBottom: "0.85rem" }}>
        <div className="chips" role="group" aria-label={t("diary.practice")}>
          {practices?.map((p) => (
            <button key={p.id} type="button" className="chip" aria-pressed={p.id === practiceId} onClick={() => setPracticeId(p.id)}>
              <span className="dot" style={{ background: p.id === practiceId ? "#fff" : colourFor(practices, p.id) }} />
              {p.name}
            </button>
          ))}
          <button type="button" className="chip" onClick={() => setNewPractice(true)} aria-label={t("practices.add")}>
            <Icon name="plus" size={16} />
          </button>
        </div>
        <div className="row wrap" style={{ marginTop: "0.75rem" }}>
          <Segmented value={unit} onChange={setUnit} label={t("editor.line_unit")}
            options={UNITS.map((u) => ({ value: u, label: t(`unit.${u}` as MessageKey) }))} />
          {unit === "hours" && (
            <label className="row" style={{ gap: "0.4rem" }}>
              <span className="label">{t("diary.hours")}</span>
              <input type="text" inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)}
                style={{ width: "4.5rem" }} aria-invalid={!DEC.test(hours.trim())} />
            </label>
          )}
          <span className="spacer" />
          {editingRate ? (
            <label className="row" style={{ gap: "0.4rem" }}>
              <span className="label">{unit === "hours" ? t("diary.rate_per_hour") : t("diary.rate")}</span>
              <input type="text" inputMode="decimal" value={rate} autoFocus placeholder="£"
                onChange={(e) => setRate(e.target.value)} onBlur={() => DEC.test(rate.trim()) && setEditingRate(false)}
                style={{ width: "6.5rem" }} aria-invalid={rate !== "" && !DEC.test(rate.trim())} />
            </label>
          ) : (
            <button type="button" className="btn ghost small" onClick={() => setEditingRate(true)} title={t("diary.change_rate")}>
              {gbp(rate)}{unit === "hours" ? ` ${t("diary.per_hour")}` : ""} ✎
            </button>
          )}
        </div>
        <p className="hint" style={{ margin: "0.6rem 0 0" }}>
          {practice ? t("diary.tap_hint", { unit: t(`unit.${unit}` as MessageKey), practice: practice.name }) : ""}
        </p>
      </div>

      <div className="month-nav">
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, -1))} aria-label={t("diary.prev_month")}><Icon name="back" /></button>
        <h2>{monthLabel(month)}</h2>
        {month !== today.slice(0, 7) && (
          <button className="btn ghost small" onClick={() => setMonth(today.slice(0, 7))}>{t("diary.this_month")}</button>
        )}
        <button className="icon-btn" onClick={() => setMonth(shiftMonth(month, 1))} aria-label={t("diary.next_month")}><Icon name="chevron" /></button>
      </div>

      <div className="cal" role="grid" aria-label={monthLabel(month)}>
        {weekdays.map((w) => <div key={w} className="cal-head" role="columnheader">{t(`diary.wd_${w}` as MessageKey)}</div>)}
        {cells.map((iso, i) => {
          if (!iso) return <div key={`x${i}`} className="day out" aria-hidden="true" />;
          const list = byDay[iso] ?? [];
          const dow = i % 7;
          const label = `${weekdayDate(iso)}${list.length ? ` — ${list.map((s) => `${t(`unit.${s.unit}` as MessageKey)} ${s.practice_name}`).join(", ")}` : ""}`;
          return (
            <button key={iso} type="button" role="gridcell" aria-label={label}
              className={`day ${iso === today ? "today" : ""} ${dow >= 5 ? "weekend" : ""}`}
              onClick={() => tapDay(iso)}>
              <span className="num">{Number(iso.slice(8))}</span>
              {list.map((s) => (
                <span key={s.id}
                  className={`s ${s.invoice ? "invoiced" : ""} ${s.status === "cancelled" ? "cancelled" : ""}`}
                  style={{ background: colourFor(practices ?? [], s.practice_id) }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen(s);
                  }}>
                  {t(`unit.${s.unit}` as MessageKey)} {initials(s.practice_name)}
                </span>
              ))}
            </button>
          );
        })}
      </div>

      <section className="card flush" style={{ marginTop: "1rem" }} aria-labelledby="h-month">
        <div className="row" style={{ padding: "0.9rem 1.15rem 0.4rem" }}>
          <h2 id="h-month" style={{ margin: 0 }}>{t("diary.month_summary", { month: monthLabel(month) })}</h2>
          <span className="spacer" />
          <span className="money muted">{gbp(monthTotal.toFixed(2))}</span>
        </div>
        <ul className="list">
          {monthReady.map((g) => (
            <li key={g.practice_id}>
              <span className="list-main">
                <span className="list-title">{g.practice_name}</span>
                <span className="list-sub">{tn("today.sessions", g.sessions)} · {gbp(g.total)} · {t("diary.not_invoiced")}</span>
              </span>
              <button className="btn small" onClick={() => createInvoice(g)}>{t("today.create_invoice")}</button>
            </li>
          ))}
          {invoicedHere.map((inv) => (
            <li key={inv.id}>
              <span className="list-main">
                <span className="list-title">{inv.invoice_number ?? t("status.draft")}</span>
                <span className="list-sub">{inv.status === "draft" ? t("diary.draft_ready") : t("diary.invoiced")}</span>
              </span>
              <Link className="btn small secondary" to={inv.status === "draft" ? `/invoices/${inv.id}/edit` : `/invoices/${inv.id}`}>
                {t("today.review")}
              </Link>
            </li>
          ))}
          {monthReady.length === 0 && invoicedHere.length === 0 && (
            <li className="muted">{sessions.length ? t("diary.future_only") : t("diary.empty_month")}</li>
          )}
        </ul>
      </section>

      {open && <SessionSheet session={open} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); void load(); }} />}
      {newPractice && (
        <PracticeSheet onClose={() => setNewPractice(false)} onSaved={(p) => {
          setPractices((ps) => [...(ps ?? []), p]);
          setPracticeId(p.id);
          setNewPractice(false);
        }} />
      )}
    </>
  );
}

function SessionSheet({ session, onClose, onChanged }: { session: WorkSession; onClose: () => void; onChanged: () => void }) {
  const { t } = useT();
  const [s, setS] = useState(session);
  const [error, setError] = useState<unknown>(null);
  const locked = session.invoice?.status === "issued";
  const save = async () => {
    try {
      await api.patch(`/sessions/${s.id}`, {
        date: s.date, unit: s.unit, quantity: s.quantity, rate: s.rate,
        pensionable: s.pensionable, description: s.description,
      });
      onChanged();
    } catch (e) {
      setError(e);
    }
  };
  const remove = async () => {
    try {
      await api.del(`/sessions/${s.id}`);
      onChanged();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Dialog open title={`${weekdayDate(session.date)} · ${session.practice_name}`} onClose={onClose}
      footer={locked ? (
        <Link className="btn" to={`/invoices/${session.invoice!.id}`}>{t("diary.open_invoice", { number: session.invoice!.invoice_number ?? "" })}</Link>
      ) : (
        <>
          <button className="btn danger" onClick={remove}>{t("common.remove")}</button>
          <button className="btn" onClick={save}>{t("common.save")}</button>
        </>
      )}>
      <ErrorAlert error={error} />
      {locked && <div className="alert info">{t("diary.locked")}</div>}
      <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0 }} className="grid">
        <Segmented value={s.unit} onChange={(u) => setS({ ...s, unit: u })} label={t("editor.line_unit")}
          options={(["am", "pm", "day", "hours", "custom"] as Unit[]).map((u) => ({ value: u, label: t(`unit.${u}` as MessageKey) }))} />
        <div className="grid grid-2">
          <Field id="ss-date" label={t("editor.line_date")}>
            <input id="ss-date" type="date" value={s.date} onChange={(e) => setS({ ...s, date: e.target.value })} />
          </Field>
          <Field id="ss-rate" label={s.unit === "hours" ? t("diary.rate_per_hour") : t("diary.rate")}>
            <input id="ss-rate" type="text" inputMode="decimal" value={s.rate} onChange={(e) => setS({ ...s, rate: e.target.value })} />
          </Field>
          {(s.unit === "hours" || s.unit === "custom") && (
            <Field id="ss-qty" label={s.unit === "hours" ? t("diary.hours") : t("editor.line_qty")}>
              <input id="ss-qty" type="text" inputMode="decimal" value={s.quantity} onChange={(e) => setS({ ...s, quantity: e.target.value })} />
            </Field>
          )}
          <Field id="ss-desc" label={t("editor.line_description")} className="span-2">
            <input id="ss-desc" type="text" value={s.description} onChange={(e) => setS({ ...s, description: e.target.value })} />
          </Field>
        </div>
        <div className="toggle-row">
          <span className="text">{t("editor.line_pensionable")}</span>
          <Toggle checked={s.pensionable} onChange={(v) => setS({ ...s, pensionable: v })} label={t("editor.line_pensionable")} />
        </div>
      </fieldset>
      {!locked && (
        <p className="hint">{t("diary.day_hint")} <button type="button" className="btn ghost small" onClick={() => setS({ ...s, date: addDays(s.date, 1) })}>{t("diary.move_next_day")}</button></p>
      )}
    </Dialog>
  );
}

export function PracticeSheet({ practice, onClose, onSaved }: { practice?: Practice; onClose: () => void; onSaved: (p: Practice) => void }) {
  const { t } = useT();
  const [p, setP] = useState({
    name: practice?.name ?? "",
    billing_address: practice?.billing_address ?? "",
    billing_email: practice?.billing_email ?? "",
    contact_name: practice?.contact_name ?? "",
    default_rate: practice?.default_rate ?? "",
    default_pensionable: practice?.default_pensionable ?? true,
    rate_includes_pension: practice?.rate_includes_pension ?? false,
    default_payment_terms_days: practice?.default_payment_terms_days?.toString() ?? "",
    practice_code: practice?.practice_code ?? "",
    is_archived: practice?.is_archived ?? false,
  });
  const [more, setMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    const body = {
      ...p,
      default_rate: p.default_rate.trim() || null,
      default_payment_terms_days: p.default_payment_terms_days.trim() ? Number(p.default_payment_terms_days) : null,
    };
    try {
      onSaved(practice
        ? await api.patch<Practice>(`/practices/${practice.id}`, body)
        : await api.post<Practice>("/practices", body));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Dialog open title={practice ? practice.name : t("practices.add")} onClose={onClose}
      footer={<button className="btn" onClick={save} disabled={!p.name.trim()}>{t("common.save")}</button>}>
      <ErrorAlert error={error} />
      <div className="grid">
        <Field id="ps-name" label={t("practices.name")}>
          <input id="ps-name" type="text" autoFocus value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} />
        </Field>
        <Field id="ps-addr" label={t("practices.billing_address")}>
          <textarea id="ps-addr" rows={3} value={p.billing_address} onChange={(e) => setP({ ...p, billing_address: e.target.value })} />
        </Field>
        <div className="grid grid-2">
          <Field id="ps-rate" label={t("welcome.session_rate")}>
            <input id="ps-rate" type="text" inputMode="decimal" placeholder="£" value={p.default_rate} onChange={(e) => setP({ ...p, default_rate: e.target.value })} />
          </Field>
          <Field id="ps-email" label={t("practices.billing_email")} optional>
            <input id="ps-email" type="email" value={p.billing_email} onChange={(e) => setP({ ...p, billing_email: e.target.value })} />
          </Field>
        </div>
        <div className="toggle-row">
          <span className="text">{t("practices.default_pensionable")}</span>
          <Toggle checked={p.default_pensionable} onChange={(v) => setP({ ...p, default_pensionable: v })} label={t("practices.default_pensionable")} />
        </div>
        {!more ? (
          <button type="button" className="btn ghost small" style={{ justifySelf: "start" }} onClick={() => setMore(true)}>{t("common.more_options")}</button>
        ) : (
          <>
            <div className="grid grid-2">
              <Field id="ps-contact" label={t("practices.contact_name")} optional>
                <input id="ps-contact" type="text" value={p.contact_name} onChange={(e) => setP({ ...p, contact_name: e.target.value })} />
              </Field>
              <Field id="ps-terms" label={t("practices.terms")} hint={t("practices.terms_hint")}>
                <input id="ps-terms" type="number" min={0} max={365} value={p.default_payment_terms_days} onChange={(e) => setP({ ...p, default_payment_terms_days: e.target.value })} />
              </Field>
              <Field id="ps-code" label={t("practices.code")} optional hint={t("practices.code_hint")}>
                <input id="ps-code" type="text" value={p.practice_code} onChange={(e) => setP({ ...p, practice_code: e.target.value.toUpperCase() })} />
              </Field>
            </div>
            <div className="toggle-row">
              <span className="text">{t("practices.rate_includes_pension")}<br /><span className="hint">{t("practices.rate_includes_pension_help")}</span></span>
              <Toggle checked={p.rate_includes_pension} onChange={(v) => setP({ ...p, rate_includes_pension: v })} label={t("practices.rate_includes_pension")} />
            </div>
            {practice && (
              <div className="toggle-row">
                <span className="text">{t("practices.archived")}</span>
                <Toggle checked={p.is_archived} onChange={(v) => setP({ ...p, is_archived: v })} label={t("practices.archived")} />
              </div>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
