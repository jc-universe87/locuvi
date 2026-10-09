import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { BookingSheet } from "../components/Booking";
import { RateFields, rateBody, rateFieldsValid } from "../components/RateFields";
import { Dialog, ErrorAlert, Field, Icon, PageHead, Segmented, Toggle, useToast } from "../components/ui";
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
  const [params] = useSearchParams();
  const initialMonth = /^\d{4}-\d{2}$/.test(params.get("month") ?? "") ? params.get("month")! : today.slice(0, 7);
  const [month, setMonth] = useState(initialMonth);
  const [practices, setPractices] = useState<Practice[] | null>(null);
  const [practiceId, setPracticeId] = useState<string | null>(remember("locuvi.diary.practice"));
  const [unit, setUnit] = useState<Unit>((remember("locuvi.diary.unit") as Unit) || "am");
  const [rate, setRate] = useState("");
  const [hours, setHours] = useState("4");
  const [editingRate, setEditingRate] = useState(false);
  const [inclusive, setInclusive] = useState(false);
  const [sessions, setSessions] = useState<WorkSession[]>([]);
  const [ready, setReady] = useState<ReadyGroup[]>([]);
  const [open, setOpen] = useState<WorkSession | null>(null);
  const [newPractice, setNewPractice] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [repeating, setRepeating] = useState(false);
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
      .get<{ rate: string | null; includes_pension: boolean; hours: string | null }>(`/sessions/suggest-rate?practice_id=${practiceId}&unit=${unit}`)
      .then((r) => {
        setRate(r.rate ?? "");
        setEditingRate(!r.rate);
        setInclusive(r.includes_pension);
        if (r.hours) setHours(r.hours);
      }, () => undefined);
  }, [practiceId, unit]);

  // An hourly practice opens on "hours"; a sessional one never stays on it by accident.
  const choosePractice = (id: string) => {
    setPracticeId(id);
    const p = practices?.find((x) => x.id === id);
    if (p?.default_unit === "hours") setUnit("hours");
    else if (p && unit === "hours") setUnit("am");
  };

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
            setUnit(p.default_unit === "hours" ? "hours" : "am");
            setNewPractice(false);
          }} />
        )}
      </>
    );
  }

  return (
    <>
      <PageHead title={t("nav.diary")}>
        <button className="btn secondary small" onClick={() => setPasting(true)}>
          <Icon name="paste" size={16} /> {t("booking.open")}
        </button>
      </PageHead>
      <ErrorAlert error={error} />

      <div className="card" style={{ paddingBottom: "0.85rem" }}>
        <div className="chips" role="group" aria-label={t("diary.practice")}>
          {practices?.map((p) => (
            <button key={p.id} type="button" className="chip" aria-pressed={p.id === practiceId} onClick={() => choosePractice(p.id)}>
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
              {gbp(rate)}{unit === "hours" ? ` ${t("diary.per_hour")}` : ""}{inclusive ? ` ${t("rates.incl")}` : ""} ✎
            </button>
          )}
        </div>
        <p className="hint row wrap" style={{ margin: "0.6rem 0 0", gap: "0.5rem" }}>
          <span style={{ flex: 1 }}>{practice ? t("diary.tap_hint", { unit: t(`unit.${unit}` as MessageKey), practice: practice.name }) : ""}</span>
          {practice && (
            <button type="button" className="btn ghost small" onClick={() => setRepeating(true)}>{t("repeat.open")}</button>
          )}
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
          setUnit(p.default_unit === "hours" ? "hours" : "am");
          setNewPractice(false);
        }} />
      )}
      <BookingSheet open={pasting} onClose={() => setPasting(false)} onChanged={() => void load()} />
      {repeating && practice && (
        <RepeatSheet practice={practice} unit={unit} rate={DEC.test(rate.trim()) ? rate.trim() : null}
          hours={unit === "hours" && DEC.test(hours.trim()) ? hours.trim() : null}
          onClose={() => setRepeating(false)} onDone={() => { setRepeating(false); void load(); }} />
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
    default_unit: (practice?.default_unit ?? "am") as string,
    hourly_rate: practice?.hourly_rate ?? "",
    default_hours: practice?.default_hours ?? "",
    default_pensionable: practice?.default_pensionable ?? true,
    rate_includes_pension: practice?.rate_includes_pension ?? false,
    default_payment_terms_days: practice?.default_payment_terms_days?.toString() ?? "",
    practice_code: practice?.practice_code ?? "",
    is_archived: practice?.is_archived ?? false,
    po_required: practice?.po_required ?? false,
    invoice_instructions: practice?.invoice_instructions ?? "",
    form_a_signatory: practice?.form_a_signatory ?? "",
  });
  const [more, setMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    const body = {
      ...p,
      ...rateBody(p),
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
      footer={<button className="btn" onClick={save} disabled={!p.name.trim() || !rateFieldsValid(p)}>{t("common.save")}</button>}>
      <ErrorAlert error={error} />
      <div className="grid">
        <Field id="ps-name" label={t("practices.name")}>
          <input id="ps-name" type="text" autoFocus value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} />
        </Field>
        <Field id="ps-addr" label={t("practices.billing_address")}>
          <textarea id="ps-addr" rows={3} value={p.billing_address} onChange={(e) => setP({ ...p, billing_address: e.target.value })} />
        </Field>
        <Field id="ps-email" label={t("practices.billing_email")} optional>
          <input id="ps-email" type="email" value={p.billing_email} onChange={(e) => setP({ ...p, billing_email: e.target.value })} />
        </Field>
        <div className="toggle-row">
          <span className="text">{t("practices.default_pensionable")}</span>
          <Toggle checked={p.default_pensionable} onChange={(v) => setP({ ...p, default_pensionable: v })} label={t("practices.default_pensionable")} />
        </div>
        <RateFields idPrefix="ps" value={p} pensionable={p.default_pensionable} onChange={(v) => setP({ ...p, ...v })} />
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
              <span className="text">{t("practices.po_required")}<br /><span className="hint">{t("practices.po_required_help")}</span></span>
              <Toggle checked={p.po_required} onChange={(v) => setP({ ...p, po_required: v })} label={t("practices.po_required")} />
            </div>
            <Field id="ps-instr" label={t("practices.instructions")} optional hint={t("practices.instructions_hint")}>
              <textarea id="ps-instr" rows={2} value={p.invoice_instructions} onChange={(e) => setP({ ...p, invoice_instructions: e.target.value })} />
            </Field>
            <Field id="ps-signatory" label={t("practices.form_a_signatory")} optional>
              <input id="ps-signatory" type="text" value={p.form_a_signatory} onChange={(e) => setP({ ...p, form_a_signatory: e.target.value })} />
            </Field>
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

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** "Every Tuesday AM at X until December" in one go; days already booked are skipped. */
function RepeatSheet({ practice, unit, rate, hours, onClose, onDone }: {
  practice: Practice; unit: Unit; rate: string | null; hours: string | null; onClose: () => void; onDone: () => void;
}) {
  const { t, tn } = useT();
  const toast = useToast();
  const today = todayLondon();
  const [days, setDays] = useState<number[]>([]);
  const [every, setEvery] = useState<"1" | "2">("1");
  const [start, setStart] = useState(today);
  const [until, setUntil] = useState(() => {
    const [y, m] = today.split("-").map(Number);
    const last = new Date(Date.UTC(y, m + 1, 0));
    return last.toISOString().slice(0, 10);
  });
  const [preview, setPreview] = useState<{ dates: string[]; skipped: string[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const body = { practice_id: practice.id, start, until, weekdays: days, every_weeks: Number(every), unit,
    ...(rate ? { rate } : {}), ...(hours ? { quantity: hours } : {}) };
  const key = JSON.stringify(body);
  useEffect(() => {
    if (!days.length || !start || !until) { setPreview(null); return; }
    const id = setTimeout(() => {
      api.post<{ dates: string[]; skipped: string[] }>("/sessions/series", { ...body, dry_run: true })
        .then((p) => { setPreview(p); setError(null); }, (e) => { setPreview(null); setError(e); });
    }, 250);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const add = async () => {
    try {
      const r = await api.post<{ created: WorkSession[]; skipped: string[] }>("/sessions/series", body);
      const ids = r.created.map((w) => w.id);
      toast({ text: tn("repeat.added", ids.length), undo: async () => {
        await api.post("/sessions/delete-many", { ids });
        onDone();
      } });
      onDone();
    } catch (e) {
      setError(e);
    }
  };
  const n = preview?.dates.length ?? 0;
  return (
    <Dialog open onClose={onClose} title={t("repeat.title", { unit: t(`unit.${unit}` as MessageKey), practice: practice.name })}
      footer={<button className="btn" disabled={!n} onClick={add}>{n ? tn("booking.add_n", n) : t("booking.add_none")}</button>}>
      <ErrorAlert error={error} />
      <div className="chips" role="group" aria-label={t("repeat.weekdays")}>
        {WEEKDAYS.map((w, i) => (
          <button key={w} type="button" className="chip" aria-pressed={days.includes(i)}
            onClick={() => setDays((d) => (d.includes(i) ? d.filter((x) => x !== i) : [...d, i]))}>
            {t(`diary.wd_${w}` as MessageKey)}
          </button>
        ))}
      </div>
      <div className="row wrap" style={{ margin: "0.9rem 0", gap: "0.75rem" }}>
        <Segmented<"1" | "2"> value={every} onChange={setEvery} label={t("repeat.every")}
          options={[{ value: "1", label: t("repeat.weekly") }, { value: "2", label: t("repeat.fortnightly") }]} />
      </div>
      <div className="row wrap" style={{ gap: "0.75rem" }}>
        <Field id="rep-from" label={t("repeat.from")}><input id="rep-from" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field id="rep-until" label={t("repeat.until")}><input id="rep-until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
      </div>
      {preview && (
        <p className="muted">
          {n ? preview.dates.map((d) => weekdayDate(d)).slice(0, 6).join(", ") + (n > 6 ? " …" : "") : t("repeat.none")}
          {preview.skipped.length > 0 && <><br />{tn("repeat.skipped", preview.skipped.length)}</>}
        </p>
      )}
      {!rate && <p className="hint">{t("repeat.usual_rate")}</p>}
    </Dialog>
  );
}
