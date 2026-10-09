import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { dateTime, dayMonth, gbp, monthLabel, pct, ukDate, weekdayDate } from "../lib/format";
import { restoreFromBin, type TrashItem } from "../lib/trash";
import { ErrorAlert, useToast } from "./ui";

type T = ReturnType<typeof useT>["t"];

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** What the owner sees for one deleted thing, worded in their language. */
export function trashTitle(t: T, item: TrashItem): string {
  const s = item.summary;
  const practice = str(s.practice) || t("trash.no_practice");
  switch (item.kind) {
    case "sessions":
      return Number(s.count) > 1
        ? t("trash.item_sessions", { n: Number(s.count), from: dayMonth(str(s.date)), to: dayMonth(str(s.last_date)), practice })
        : t("trash.item_session", { date: weekdayDate(str(s.date)), unit: t(`unit.${str(s.unit) || "am"}` as MessageKey), practice });
    case "invoice":
      return t("trash.item_invoice", { practice, total: gbp(str(s.total) || "0.00") });
    case "payment": {
      const amount = str(s.amount).replace(/^-/, "");
      return t(s.refund ? "trash.item_refund" : "trash.item_payment", { amount: gbp(amount), number: str(s.invoice_number) });
    }
    case "pension_policy":
      return t("trash.item_policy", { rate: pct(str(s.employer_rate)), date: ukDate(str(s.effective_from)) });
    case "pension_submission":
      return t("trash.item_submission", { month: monthLabel(str(s.month)) });
    case "document":
      return t("trash.item_document", { title: item.label || str(s.filename) });
    case "mailbox":
      return t("trash.item_mailbox", { name: item.label });
    default:
      return item.label;
  }
}

export function TrashSection() {
  const { t, tn } = useT();
  const toast = useToast();
  const [items, setItems] = useState<TrashItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = () => api.get<{ items: TrashItem[] }>("/trash").then((r) => setItems(r.items), setError);
  useEffect(() => {
    void load();
  }, []);
  const restore = async (id: string) => {
    setBusy(id);
    await restoreFromBin(id, t, tn, toast);
    setBusy(null);
    await load();
  };
  return (
    <>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("trash.intro")}</p>
      <ErrorAlert error={error} />
      {items && items.length === 0 && <p className="hint">{t("trash.empty")}</p>}
      {items && items.length > 0 && (
        <div className="form-list">
          {items.map((x) => (
            <div key={x.id} className="list-row">
              <span className="list-main">
                <span className="list-title">{trashTitle(t, x)}</span>
                <span className="list-sub">{t("trash.deleted_on", { when: dateTime(x.deleted_at), date: ukDate(x.purge_on) })}</span>
              </span>
              <button className="btn secondary small" disabled={busy !== null} onClick={() => void restore(x.id)}>
                {t("trash.restore")}
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
