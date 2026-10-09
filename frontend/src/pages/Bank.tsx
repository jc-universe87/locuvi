import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorAlert, Icon, PageHead, Segmented, useToast } from "../components/ui";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { gbp, ukDate } from "../lib/format";
import type { BankTx, InvoiceSummary } from "../lib/types";

type Filter = "todo" | "matched" | "ignored";
type Counts = { suggested: number; unmatched: number; matched: number; ignored: number };

/** Payments in: import a bank statement, confirm the matches Locuvi found, pick the rest. */
export default function BankPage() {
  const { t, tn } = useT();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("todo");
  const [txs, setTxs] = useState<BankTx[] | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [unpaid, setUnpaid] = useState<InvoiceSummary[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const status = filter === "todo" ? "" : `?status=${filter}`;
      const [r, inv] = await Promise.all([
        api.get<{ transactions: BankTx[]; counts: Counts }>(`/bank/transactions${status}`),
        api.get<{ items: InvoiceSummary[] }>("/invoices?payment=unpaid,part_paid,overdue&page_size=100"),
      ]);
      setTxs(filter === "todo" ? r.transactions.filter((x) => x.status === "suggested" || x.status === "unmatched") : r.transactions);
      setCounts(r.counts);
      setUnpaid(inv.items);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [filter]);
  useEffect(() => void load(), [load]);

  const act = async (fn: () => Promise<unknown>, text?: string, undo?: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (text) toast({ text, undo: undo ? () => void undo().then(load) : undefined });
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const importFile = (f: File) => act(async () => {
    const form = new FormData();
    form.append("file", f, f.name);
    const r = await api.upload<{ new: number; suggested: number; unmatched: number }>("/bank/import", form);
    toast({ text: tn("bank.imported", r.new, { m: r.suggested }) });
    setFilter("todo");
  });
  const high = (txs ?? []).filter((x) => x.status === "suggested" && x.suggestion?.confidence === "high").length;

  return (
    <>
      <PageHead title={t("bank.title")}>
        <button className="btn small" onClick={() => file.current?.click()} disabled={busy}>
          <Icon name="upload" size={16} /> {t("bank.import")}
        </button>
      </PageHead>
      <input ref={file} type="file" accept=".csv,text/csv" hidden aria-label={t("bank.import")}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void importFile(f); e.target.value = ""; }} />
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("bank.intro")}</p>
      <ErrorAlert error={error} />

      <div className="row wrap" style={{ marginBottom: "0.9rem" }}>
        <Segmented<Filter> value={filter} onChange={setFilter} label={t("bank.filter")} options={[
          { value: "todo", label: `${t("bank.filter_todo")}${counts ? ` (${counts.suggested + counts.unmatched})` : ""}` },
          { value: "matched", label: t("bank.filter_matched") },
          { value: "ignored", label: t("bank.filter_ignored") },
        ]} />
        <span className="spacer" />
        {filter === "todo" && high > 0 && (
          <button className="btn small" disabled={busy}
            onClick={() => act(() => api.post("/bank/transactions/accept-all"), tn("bank.confirmed", high))}>
            <Icon name="check" size={16} /> {tn("bank.confirm_all", high)}
          </button>
        )}
      </div>

      {txs && txs.length === 0 && (
        <div className="card empty">
          <div className="big" aria-hidden="true">🏦</div>
          <p>{filter === "todo" ? t("bank.empty") : t("bank.none")}</p>
          {filter === "todo" && <p className="faint">{t("bank.how")}</p>}
        </div>
      )}
      {txs && txs.length > 0 && (
        <div className="card flush">
          {txs.map((x) => (
            <TxRow key={x.id} tx={x} unpaid={unpaid} busy={busy}
              onAccept={(ids) => act(() => api.post(`/bank/transactions/${x.id}/accept`, { invoice_ids: ids }),
                t("bank.recorded"), () => api.post(`/bank/transactions/${x.id}/undo`))}
              onIgnore={() => act(() => api.post(`/bank/transactions/${x.id}/ignore`), t("bank.ignored"),
                () => api.post(`/bank/transactions/${x.id}/undo`))}
              onUndo={() => act(() => api.post(`/bank/transactions/${x.id}/undo`))} />
          ))}
        </div>
      )}
    </>
  );
}

function TxRow({ tx, unpaid, busy, onAccept, onIgnore, onUndo }: {
  tx: BankTx;
  unpaid: InvoiceSummary[];
  busy: boolean;
  onAccept: (ids: string[] | null) => void;
  onIgnore: () => void;
  onUndo: () => void;
}) {
  const { t } = useT();
  const [pick, setPick] = useState("");
  const s = tx.suggestion;
  return (
    <div className="task" style={{ alignItems: "flex-start" }}>
      <span className={`task-icon ${tx.status === "matched" ? "ok" : ""}`}><Icon name="money" /></span>
      <span className="list-main">
        <span className="list-title">{gbp(tx.amount)} · {ukDate(String(tx.booked_on))}</span>
        <span className="list-sub">{tx.description || "—"}</span>
        {s && tx.status === "suggested" && (
          <span className="list-sub" style={{ color: "var(--ink)", marginTop: "0.25rem" }}>
            → {s.invoices.map((i) => `${i.number} (${i.practice}) ${gbp(i.amount)}`).join(" + ")}
            {" "}<span className={`pill ${s.confidence === "high" ? "ok" : "warn"}`}>{t(`bank.kind_${s.kind}` as MessageKey)}</span>
          </span>
        )}
        {tx.status === "unmatched" && (
          <span className="row wrap" style={{ gap: "0.4rem", marginTop: "0.4rem" }}>
            <select aria-label={t("bank.pick")} value={pick} onChange={(e) => setPick(e.target.value)} style={{ flex: "1 1 14rem" }}>
              <option value="">{t("bank.pick")}</option>
              {unpaid.map((i) => (
                <option key={i.id} value={i.id}>{i.invoice_number} · {i.practice_name} · {gbp(i.payment.outstanding ?? i.grand_total)}</option>
              ))}
            </select>
            <button className="btn small" disabled={!pick || busy} onClick={() => onAccept([pick])}>{t("bank.record")}</button>
          </span>
        )}
      </span>
      <span className="actions" style={{ flex: "none" }}>
        {tx.status === "suggested" && <button className="btn small" disabled={busy} onClick={() => onAccept(null)}>{t("bank.confirm")}</button>}
        {(tx.status === "suggested" || tx.status === "unmatched") && (
          <button className="btn ghost small" disabled={busy} onClick={onIgnore}>{t("bank.ignore")}</button>
        )}
        {(tx.status === "matched" || tx.status === "ignored") && (
          <button className="btn ghost small" disabled={busy} onClick={onUndo}>{t("common.undo")}</button>
        )}
      </span>
    </div>
  );
}
