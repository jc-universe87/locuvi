import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Dialog, ErrorAlert, Field, SavedIndicator, Toggle, useIssueText } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api, downloadBlob, newIdempotencyKey, openPendingTab } from "../lib/api";
import { addDays, gbp, pct, todayLondon } from "../lib/format";
import type { Analysis, InvoiceDetail, Line, Numbering, Practice, Profile, Unit } from "../lib/types";

const UNITS: Unit[] = ["am", "pm", "day", "hours", "custom"];

interface Form {
  practice_id: string;
  invoice_date: string;
  due_date: string;
  reference: string;
  notes: string;
  pension_enabled: boolean;
  lines: Line[];
}

const emptyForm: Form = {
  practice_id: "",
  invoice_date: "",
  due_date: "",
  reference: "",
  notes: "",
  pension_enabled: true,
  lines: [],
};

const DEC = /^\d+(\.\d{1,2})?$/;

function lineValid(l: Line) {
  return !!l.service_date && DEC.test(l.unit_price.trim()) && DEC.test(l.quantity.trim()) && Number(l.quantity) > 0;
}

function toBody(f: Form) {
  return {
    practice_id: f.practice_id || null,
    invoice_date: f.invoice_date || null,
    due_date: f.due_date || null,
    reference: f.reference || null,
    notes: f.notes || null,
    pension_enabled: f.pension_enabled,
    lines: f.lines.map((l) => ({
      service_date: l.service_date,
      description: l.description,
      unit: l.unit,
      quantity: l.quantity.trim(),
      unit_price: l.unit_price.trim(),
      pensionable: l.pensionable,
    })),
  };
}

function fromDetail(d: InvoiceDetail): Form {
  return {
    practice_id: d.practice_id ?? "",
    invoice_date: d.invoice_date ?? "",
    due_date: d.due_date ?? "",
    reference: d.reference ?? "",
    notes: d.notes ?? "",
    pension_enabled: d.pension_enabled,
    lines: d.lines.map((l) => ({ ...l })),
  };
}

export default function InvoiceEditor() {
  const { t } = useT();
  const fmtIssue = useIssueText();
  const nav = useNavigate();
  const { id } = useParams();
  const [form, setForm] = useState<Form>(emptyForm);
  const [dirty, setDirty] = useState(false);
  const [practices, setPractices] = useState<Practice[]>([]);
  const [numbering, setNumbering] = useState<Numbering | null>(null);
  const [saved, setSaved] = useState<InvoiceDetail | null>(null);
  const [calc, setCalc] = useState<Analysis | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmIssue, setConfirmIssue] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [newPractice, setNewPractice] = useState(false);
  const issueKey = useRef<string | null>(null);
  const touched = useRef(false);

  const practice = practices.find((p) => p.id === form.practice_id) ?? null;

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ps, nb] = await Promise.all([
          api.get<Practice[]>("/practices"),
          api.get<Numbering>("/settings/numbering"),
        ]);
        if (cancelled) return;
        setPractices(ps);
        setNumbering(nb);
        if (id) {
          const d = await api.get<InvoiceDetail>(`/invoices/${id}`);
          if (cancelled) return;
          if (d.status !== "draft") {
            nav(`/invoices/${id}`, { replace: true });
            return;
          }
          if (d.practice_id && !ps.some((p) => p.id === d.practice_id)) {
            setPractices([...ps, await api.get<Practice>(`/practices/${d.practice_id}`)]);
          }
          setSaved(d);
          setForm(fromDetail(d));
          setDirty(false);
        } else {
          const profile = await api.get<Profile>("/settings/profile");
          // Only apply the default if the user has not touched the form meanwhile.
          if (!cancelled && !touched.current) {
            setForm((f) => ({ ...f, pension_enabled: profile.pension_default_enabled }));
          }
        }
      } catch (e) {
        if (!cancelled) setError(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, nav]);

  // Live, server-side calculation (authoritative Decimal maths).
  const validIdx = useMemo(() => form.lines.map((l, i) => (lineValid(l) ? i : -1)).filter((i) => i >= 0), [form.lines]);
  useEffect(() => {
    const handle = setTimeout(async () => {
      try {
        const body = toBody(form);
        const res = await api.post<Analysis>("/invoices/calculate", {
          practice_id: body.practice_id,
          pension_enabled: body.pension_enabled,
          lines: validIdx.map((i) => body.lines[i]),
        });
        setCalc(res);
      } catch {
        /* incomplete input: keep last result */
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [form, validIdx]);

  const amountFor = (i: number) => {
    const pos = validIdx.indexOf(i);
    return pos >= 0 && calc ? calc.totals.line_amounts[pos] : null;
  };

  const update = (patch: Partial<Form> | ((f: Form) => Partial<Form>)) => {
    touched.current = true;
    setForm((f) => ({ ...f, ...(typeof patch === "function" ? patch(f) : patch) }));
    setDirty(true);
    setNotice(null);
  };
  const updateLine = (i: number, patch: Partial<Line>) =>
    update((f) => ({ lines: f.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));

  const addLine = () =>
    update((f) => {
      const last = f.lines[f.lines.length - 1];
    const unit: Unit = last?.unit ?? practice?.default_unit ?? "am";
    const next: Line = last
      ? { ...last, id: undefined, amount: undefined, service_date: last.service_date ? addDays(last.service_date, 1) : todayLondon() }
      : {
          service_date: todayLondon(),
          unit,
          description: t(`editor.default_desc_${unit}` as MessageKey),
          quantity: "1",
          unit_price: practice?.default_rate ?? "",
          pensionable: practice?.default_pensionable ?? true,
        };
      return { lines: [...f.lines, next] };
    });

  const save = useCallback(async (): Promise<InvoiceDetail | null> => {
    setBusy("save");
    setError(null);
    try {
      const body = toBody(form);
      const d = saved
        ? await api.patch<InvoiceDetail>(`/invoices/${saved.id}`, body)
        : await api.post<InvoiceDetail>("/invoices", body);
      setSaved(d);
      setDirty(false);
      if (!saved) nav(`/invoices/${d.id}/edit`, { replace: true });
      return d;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setBusy(null);
    }
  }, [form, saved, nav]);

  // Drafts save themselves: shortly after any change, once every line is valid.
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  useEffect(() => {
    if (!dirty || busy !== null) return;
    if (!saved && !form.practice_id && form.lines.length === 0) return;
    if (!form.lines.every(lineValid)) return;
    const h = setTimeout(async () => {
      setSaveState("saving");
      const d = await save();
      setSaveState(d ? "saved" : "error");
      if (d) setTimeout(() => setSaveState((x) => (x === "saved" ? "idle" : x)), 1800);
    }, 900);
    return () => clearTimeout(h);
  }, [dirty, form, saved, busy, save]);

  const preview = async () => {
    const tab = openPendingTab(); // must happen before any await
    const d = dirty || !saved ? await save() : saved;
    if (!d) {
      tab.close();
      return;
    }
    setBusy("preview");
    try {
      tab.show(await api.blob("POST", `/invoices/${d.id}/preview`));
    } catch (e) {
      tab.close();
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const startIssue = async () => {
    const d = dirty || !saved ? await save() : saved;
    if (!d) return;
    if (d.analysis && d.analysis.blocking.length > 0) return; // shown in the panel
    try {
      setNumbering(await api.get<Numbering>("/settings/numbering"));
    } catch {
      /* keep previous preview */
    }
    issueKey.current = newIdempotencyKey();
    setConfirmIssue(true);
  };

  const doIssue = async () => {
    if (!saved || !issueKey.current) return;
    setBusy("issue");
    setError(null);
    try {
      const d = await api.post<InvoiceDetail>(`/invoices/${saved.id}/issue`, {}, { "Idempotency-Key": issueKey.current });
      try {
        downloadBlob(await api.blob("GET", `/invoices/${d.id}/pdf`), `${d.invoice_number}.pdf`);
      } catch {
        /* the detail page offers the download */
      }
      nav(`/invoices/${d.id}`, { state: { issued: d.invoice_number } });
    } catch (e) {
      setError(e);
      setConfirmIssue(false);
      try {
        // The issue may have committed even though the response was lost: if so, go to it.
        const fresh = await api.get<InvoiceDetail>(`/invoices/${saved.id}`);
        if (fresh.status !== "draft") {
          nav(`/invoices/${fresh.id}`, { replace: true, state: { issued: fresh.invoice_number } });
          return;
        }
        setSaved(fresh);
      } catch {
        /* ignore */
      }
    } finally {
      setBusy(null);
    }
  };

  const split = async () => {
    const d = dirty || !saved ? await save() : saved;
    if (!d) return;
    try {
      const res = await api.post<{ invoices: { id: string }[] }>(`/invoices/${d.id}/split-by-month`);
      const fresh = await api.get<InvoiceDetail>(`/invoices/${d.id}`);
      setSaved(fresh);
      setForm(fromDetail(fresh));
      setDirty(false);
      setNotice(t("editor.split_done", { n: res.invoices.length }));
    } catch (e) {
      setError(e);
    }
  };

  const deleteDraft = async () => {
    if (!saved) return;
    try {
      await api.del(`/invoices/${saved.id}`);
      nav("/invoices");
    } catch (e) {
      setError(e);
    }
  };

  const totals = calc?.totals;
  const savedBlocking = !dirty && saved?.analysis ? saved.analysis.blocking : [];
  const liveBlocking = calc?.blocking ?? [];
  const blocking = [...liveBlocking, ...savedBlocking.filter((b) => !liveBlocking.some((l) => l.code === b.code))];
  const warnings = calc?.warnings ?? [];
  const multiMonth = blocking.some((b) => b.code === "invoice.pensionable_multi_month");

  return (
    <>
      <div className="row" style={{ alignItems: "baseline" }}>
        <h1>{saved ? t("editor.title_draft") : t("editor.title_new")}</h1>
        <SavedIndicator state={saveState === "error" ? "idle" : saveState} />
      </div>
      <ErrorAlert error={error} />
      {notice && <div className="alert ok" role="status">{notice}</div>}

      <div className="editor">
        <div>
          <section className="card" aria-labelledby="h-details">
            <h2 id="h-details" className="sr-only">{t("editor.details")}</h2>
            <div className="grid grid-2">
              <Field id="practice" label={t("editor.practice")} className="span-2">
                <div className="actions" style={{ flexWrap: "nowrap" }}>
                  <select id="practice" value={form.practice_id} onChange={(e) => update({ practice_id: e.target.value })}>
                    <option value="">{t("editor.choose_practice")}</option>
                    {practices.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <button type="button" className="btn secondary" onClick={() => setNewPractice(true)} style={{ whiteSpace: "nowrap" }}>
                    + {t("editor.new_practice")}
                  </button>
                </div>
              </Field>
              <Field id="invoice_date" label={t("editor.issue_date")} hint={t("editor.issue_date_hint")}>
                <input id="invoice_date" type="date" value={form.invoice_date} onChange={(e) => update({ invoice_date: e.target.value })} />
              </Field>
              <Field id="due_date" label={t("editor.due_date")} hint={t("editor.due_date_hint")}>
                <input id="due_date" type="date" value={form.due_date} onChange={(e) => update({ due_date: e.target.value })} />
              </Field>
              <Field id="reference" label={t("editor.reference")} optional className="span-2">
                <input id="reference" type="text" maxLength={100} value={form.reference} onChange={(e) => update({ reference: e.target.value })} />
              </Field>
            </div>
          </section>

          <section className="card" aria-labelledby="h-lines">
            <h2 id="h-lines">{t("editor.lines")}</h2>
            <div className="toggle-row" style={{ marginBottom: "0.9rem" }}>
              <span className="text">
                {t("editor.pension_enabled")}
                <br />
                <span className="hint">{t("editor.pension_help")}</span>
              </span>
              <Toggle checked={form.pension_enabled} onChange={(v) => update({ pension_enabled: v })} label={t("editor.pension_enabled")} />
            </div>
            {form.lines.length === 0 && <p className="muted">{t("editor.no_lines")}</p>}
            <div className="lines">
              {form.lines.map((l, i) => {
                const n = i + 1;
                const amount = amountFor(i);
                return (
                  <fieldset key={i} className="line" style={{ margin: 0 }}>
                    <legend className="sr-only">{t("editor.line_n", { n })}</legend>
                    <Field id={`d${i}`} label={t("editor.line_date")}>
                      <input id={`d${i}`} type="date" value={l.service_date} required onChange={(e) => updateLine(i, { service_date: e.target.value })} />
                    </Field>
                    <Field id={`u${i}`} label={t("editor.line_unit")}>
                      <select id={`u${i}`} value={l.unit} onChange={(e) => updateLine(i, { unit: e.target.value as Unit })}>
                        {UNITS.map((u) => (
                          <option key={u} value={u}>{t(`unit.${u}` as MessageKey)}</option>
                        ))}
                      </select>
                    </Field>
                    <Field id={`desc${i}`} label={t("editor.line_description")} className="desc">
                      <input id={`desc${i}`} type="text" maxLength={300} value={l.description} onChange={(e) => updateLine(i, { description: e.target.value })} />
                    </Field>
                    <Field id={`q${i}`} label={t("editor.line_qty")}>
                      <input id={`q${i}`} type="text" inputMode="decimal" value={l.quantity}
                        aria-invalid={!DEC.test(l.quantity.trim())}
                        onChange={(e) => updateLine(i, { quantity: e.target.value })} />
                    </Field>
                    <Field id={`r${i}`} label={t("editor.line_rate")}>
                      <input id={`r${i}`} type="text" inputMode="decimal" value={l.unit_price}
                        aria-invalid={l.unit_price !== "" && !DEC.test(l.unit_price.trim())}
                        onChange={(e) => updateLine(i, { unit_price: e.target.value })} />
                    </Field>
                    <div className="line-foot">
                      <label className="check">
                        <input type="checkbox" checked={l.pensionable} disabled={!form.pension_enabled}
                          onChange={(e) => updateLine(i, { pensionable: e.target.checked })} />
                        <span>{t("editor.line_pensionable")}</span>
                      </label>
                      <span className="actions">
                        <span className="money amount" aria-label={t("editor.line_amount")}>{gbp(amount)}</span>
                        <button type="button" className="btn ghost small" onClick={() => update((f) => ({ lines: f.lines.filter((_, j) => j !== i) }))}
                          aria-label={t("editor.line_remove", { n })}>
                          {t("common.remove")}
                        </button>
                      </span>
                    </div>
                  </fieldset>
                );
              })}
            </div>
            <div className="actions" style={{ marginTop: "0.75rem" }}>
              <button type="button" className="btn secondary" onClick={addLine}>+ {t("editor.add_line")}</button>
            </div>
          </section>

          <section className="card">
            <Field id="notes" label={t("editor.notes")} optional>
              <textarea id="notes" maxLength={2000} value={form.notes} onChange={(e) => update({ notes: e.target.value })} />
            </Field>
          </section>
        </div>

        <aside className="card summary" aria-labelledby="h-summary">
          <h2 id="h-summary">{t("totals.title")}</h2>
          <div aria-live="polite">
            <dl>
              {totals && totals.pensionable_basic_total !== "0.00" && (
                <>
                  <dt>{t("totals.basic")}</dt>
                  <dd className="money">{gbp(totals.pensionable_basic_total)}</dd>
                  {totals.non_pensionable_total !== "0.00" && (
                    <>
                      <dt>{t("totals.other")}</dt>
                      <dd className="money">{gbp(totals.non_pensionable_total)}</dd>
                    </>
                  )}
                </>
              )}
              <dt>{t("totals.subtotal")}</dt>
              <dd className="money">{gbp(totals?.fee_subtotal ?? "0.00")}</dd>
              {totals && totals.employer_rate && totals.pensionable_basic_total !== "0.00" && (
                <>
                  <dt className="sub">{t("totals.pensionable_pay", { fraction: pct(totals.pensionable_fraction) })}</dt>
                  <dd className="money sub muted">{gbp(totals.pensionable_pay)}</dd>
                  <dt>{t("totals.employer", { rate: pct(totals.employer_rate) })}</dt>
                  <dd className="money">{gbp(totals.employer_contribution)}</dd>
                </>
              )}
              <div className="total" style={{ display: "contents" }}>
                <dt>{t("totals.total")}</dt>
                <dd className="money">{gbp(totals?.grand_total ?? "0.00")}</dd>
              </div>
            </dl>
            {calc?.policy && <p className="hint">{t("totals.policy", { label: calc.policy.label })}</p>}
            <p className="hint">{t("totals.no_vat")}</p>
          </div>

          {warnings.length > 0 && (
            <div className="alert warn" role="status">
              <strong>{t("warning.title")}</strong>
              <ul>{warnings.map((w, i) => <li key={i}>{fmtIssue(w)}</li>)}</ul>
            </div>
          )}
          {blocking.length > 0 && (
            <div className="alert error">
              <strong>{t("editor.cannot_issue")}</strong>
              <ul>{blocking.map((b, i) => <li key={i}>{fmtIssue(b)}</li>)}</ul>
              {multiMonth && (
                <button type="button" className="btn secondary small" style={{ marginTop: "0.5rem" }} onClick={split}>
                  {t("editor.split")}
                </button>
              )}
            </div>
          )}

          <div className="grid" style={{ marginTop: "0.75rem" }}>
            <button className="btn big" onClick={startIssue} disabled={busy === "issue" || blocking.length > 0 || form.lines.length === 0}>
              {t("editor.issue")}
            </button>
            <button className="btn secondary" onClick={preview} disabled={busy === "preview" || form.lines.length === 0}>
              {t("editor.preview")}
            </button>
            <p className="hint" style={{ margin: 0, textAlign: "center" }}>{t("editor.autosave_hint")}</p>
            {saved && (
              <button className="btn ghost small" style={{ color: "var(--err)" }} onClick={() => setConfirmDelete(true)}>{t("editor.delete_draft")}</button>
            )}
          </div>
        </aside>
      </div>

      <div className="mobile-total" aria-hidden="true">
        <span>
          <span className="muted">{t("totals.total")} </span>
          <strong className="money">{gbp(totals?.grand_total ?? "0.00")}</strong>
        </span>
        <button className="btn small" onClick={startIssue} disabled={busy !== null || blocking.length > 0 || form.lines.length === 0} tabIndex={-1}>
          {t("editor.issue")}
        </button>
      </div>

      <Dialog
        open={confirmIssue}
        title={t("issue.confirm_title")}
        onClose={() => setConfirmIssue(false)}
        footer={
          <>
            <button className="btn secondary" onClick={() => setConfirmIssue(false)} disabled={busy === "issue"}>{t("common.cancel")}</button>
            <button className="btn" onClick={doIssue} disabled={busy === "issue"}>
              {busy === "issue" ? t("issue.issuing") : t("issue.confirm_button")}
            </button>
          </>
        }
      >
        <p>{t("issue.confirm_body")}</p>
        <ul>
          {numbering && <li>{t("issue.confirm_number", { number: numbering.preview })}</li>}
          <li><strong>{t("issue.confirm_total", { total: gbp(saved?.analysis?.totals.grand_total ?? totals?.grand_total) })}</strong></li>
          <li>
            {saved?.analysis && saved.analysis.totals.employer_contribution !== "0.00"
              ? t("issue.confirm_pension", { amount: gbp(saved.analysis.totals.employer_contribution) })
              : t("issue.confirm_no_pension")}
          </li>
        </ul>
      </Dialog>

      <Dialog
        open={confirmDelete}
        title={t("editor.delete_draft")}
        onClose={() => setConfirmDelete(false)}
        footer={
          <>
            <button className="btn secondary" onClick={() => setConfirmDelete(false)}>{t("common.cancel")}</button>
            <button className="btn danger" onClick={deleteDraft}>{t("common.delete")}</button>
          </>
        }
      >
        <p>{t("editor.delete_confirm")}</p>
      </Dialog>

      {newPractice && (
        <NewPracticeDialog
          onClose={() => setNewPractice(false)}
          onCreated={(p) => {
            setPractices((ps) => [...ps, p].sort((a, b) => a.name.localeCompare(b.name)));
            update({ practice_id: p.id });
            setNewPractice(false);
          }}
        />
      )}
    </>
  );
}

function NewPracticeDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Practice) => void }) {
  const { t } = useT();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [rate, setRate] = useState("");
  const [error, setError] = useState<unknown>(null);
  const create = async () => {
    try {
      onCreated(await api.post<Practice>("/practices", { name, billing_address: address, default_rate: rate || null }));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Dialog
      open
      title={t("editor.new_practice")}
      onClose={onClose}
      footer={
        <>
          <button className="btn secondary" onClick={onClose}>{t("common.cancel")}</button>
          <button className="btn" onClick={create} disabled={!name.trim()}>{t("common.add")}</button>
        </>
      }
    >
      <ErrorAlert error={error} />
      <div className="grid">
        <Field id="np-name" label={t("practices.name")}>
          <input id="np-name" type="text" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field id="np-addr" label={t("practices.billing_address")}>
          <textarea id="np-addr" value={address} onChange={(e) => setAddress(e.target.value)} />
        </Field>
        <Field id="np-rate" label={t("practices.default_rate")} optional>
          <input id="np-rate" type="text" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}
