import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ErrorAlert, Field } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { gbp } from "../lib/format";
import type { Practice, Unit } from "../lib/types";

type Draft = Omit<Practice, "id" | "default_payment_terms_days" | "default_rate"> & {
  default_rate: string;
  default_payment_terms_days: string;
};

const blank: Draft = {
  name: "",
  billing_address: "",
  billing_email: "",
  contact_name: "",
  reference: "",
  default_rate: "",
  default_unit: "am",
  default_pensionable: true,
  rate_includes_pension: false,
  default_payment_terms_days: "",
  is_archived: false,
};

export default function PracticesPage() {
  const { t } = useT();
  const [list, setList] = useState<Practice[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<{ id: string | null; draft: Draft } | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setList(await api.get<Practice[]>(`/practices?include_archived=${showArchived}`));
    } catch (e) {
      setError(e);
    }
  }, [showArchived]);
  useEffect(() => {
    void load();
  }, [load]);

  const edit = (p: Practice | null) => {
    setError(null);
    setEditing({
      id: p?.id ?? null,
      draft: p
        ? {
            ...p,
            billing_email: p.billing_email ?? "",
            contact_name: p.contact_name ?? "",
            reference: p.reference ?? "",
            default_rate: p.default_rate ?? "",
            default_payment_terms_days: p.default_payment_terms_days?.toString() ?? "",
          }
        : blank,
    });
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    const d = editing.draft;
    const body = {
      ...d,
      default_rate: d.default_rate.trim() || null,
      default_payment_terms_days: d.default_payment_terms_days.trim() ? Number(d.default_payment_terms_days) : null,
    };
    try {
      if (editing.id) await api.patch(`/practices/${editing.id}`, body);
      else await api.post("/practices", body);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err);
    }
  };

  const set = (patch: Partial<Draft>) => editing && setEditing({ ...editing, draft: { ...editing.draft, ...patch } });

  return (
    <>
      <div className="page-head">
        <h1>{t("practices.title")}</h1>
        <span className="spacer" />
        <label className="check">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          <span>{t("practices.show_archived")}</span>
        </label>
        <button className="btn" onClick={() => edit(null)}>+ {t("practices.add")}</button>
      </div>
      <ErrorAlert error={error} />

      {editing && (
        <form className="card" onSubmit={save} aria-labelledby="h-practice">
          <h2 id="h-practice">{editing.id ? t("practices.edit") : t("practices.add")}</h2>
          <div className="grid grid-2">
            <Field id="p-name" label={t("practices.name")} className="span-2">
              <input id="p-name" type="text" required maxLength={200} value={editing.draft.name} onChange={(e) => set({ name: e.target.value })} />
            </Field>
            <Field id="p-addr" label={t("practices.billing_address")} className="span-2">
              <textarea id="p-addr" value={editing.draft.billing_address} onChange={(e) => set({ billing_address: e.target.value })} />
            </Field>
            <Field id="p-email" label={t("practices.billing_email")} optional>
              <input id="p-email" type="email" value={editing.draft.billing_email ?? ""} onChange={(e) => set({ billing_email: e.target.value })} />
            </Field>
            <Field id="p-contact" label={t("practices.contact_name")} optional>
              <input id="p-contact" type="text" value={editing.draft.contact_name ?? ""} onChange={(e) => set({ contact_name: e.target.value })} />
            </Field>
            <Field id="p-ref" label={t("practices.reference")} optional>
              <input id="p-ref" type="text" value={editing.draft.reference ?? ""} onChange={(e) => set({ reference: e.target.value })} />
            </Field>
            <Field id="p-terms" label={t("practices.terms")} hint={t("practices.terms_hint")}>
              <input id="p-terms" type="number" min={0} max={365} value={editing.draft.default_payment_terms_days}
                onChange={(e) => set({ default_payment_terms_days: e.target.value })} />
            </Field>
            <Field id="p-rate" label={t("practices.default_rate")} optional>
              <input id="p-rate" type="text" inputMode="decimal" value={editing.draft.default_rate} onChange={(e) => set({ default_rate: e.target.value })} />
            </Field>
            <Field id="p-unit" label={t("practices.default_unit")}>
              <select id="p-unit" value={editing.draft.default_unit} onChange={(e) => set({ default_unit: e.target.value as Unit })}>
                {(["am", "pm", "day", "hours", "custom"] as Unit[]).map((u) => (
                  <option key={u} value={u}>{t(`unit.${u}` as MessageKey)}</option>
                ))}
              </select>
            </Field>
            <label className="check span-2">
              <input type="checkbox" checked={editing.draft.default_pensionable} onChange={(e) => set({ default_pensionable: e.target.checked })} />
              <span>{t("practices.default_pensionable")}</span>
            </label>
            <label className="check span-2">
              <input type="checkbox" checked={editing.draft.rate_includes_pension} onChange={(e) => set({ rate_includes_pension: e.target.checked })} />
              <span>
                {t("practices.rate_includes_pension")}
                <br />
                <span className="hint">{t("practices.rate_includes_pension_help")}</span>
              </span>
            </label>
            {editing.id && (
              <label className="check span-2">
                <input type="checkbox" checked={editing.draft.is_archived} onChange={(e) => set({ is_archived: e.target.checked })} />
                <span>{t("practices.archived")}</span>
              </label>
            )}
          </div>
          <div className="actions" style={{ marginTop: "1rem" }}>
            <button className="btn">{t("common.save")}</button>
            <button type="button" className="btn secondary" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
          </div>
        </form>
      )}

      <div className="card">
        {list.length === 0 && <p className="muted">{t("practices.empty")}</p>}
        {list.length > 0 && (
          <div className="table-wrap">
            <table className="list">
              <thead>
                <tr>
                  <th>{t("practices.name")}</th>
                  <th className="money">{t("practices.default_rate")}</th>
                  <th>{t("practices.default_unit")}</th>
                  <th><span className="sr-only">{t("common.edit")}</span></th>
                </tr>
              </thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.name}</strong>
                      {p.is_archived && <span className="muted"> · {t("practices.archived")}</span>}
                      <div className="muted" style={{ fontSize: "0.85rem" }}>{p.billing_address.split("\n")[0]}</div>
                    </td>
                    <td className="money">{p.default_rate ? gbp(p.default_rate) : t("common.none")}</td>
                    <td>{t(`unit.${p.default_unit}` as MessageKey)}</td>
                    <td><button className="btn ghost small" onClick={() => edit(p)}>{t("common.edit")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
