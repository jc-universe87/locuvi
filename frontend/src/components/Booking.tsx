import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";
import { gbp, weekdayDate } from "../lib/format";
import type { AssistantConfig, Practice, Proposal, ProposalItem } from "../lib/types";
import { Dialog, ErrorAlert, Icon, useToast } from "./ui";

const DEC = /^\d+(\.\d{1,2})?$/;

interface Edit {
  checked: boolean;
  practice_id: string | null;
  rate: string;
}

function initialEdits(p: Proposal): Edit[] {
  return p.items.map((i) => ({ checked: i.selected, practice_id: i.practice_id, rate: i.rate ?? "" }));
}

/** The one place a suggestion becomes diary entries: tick, adjust, "Add N sessions". */
export function ProposalReview({
  proposal,
  practices,
  onDone,
}: {
  proposal: Proposal;
  practices: Practice[];
  onDone: (p: Proposal | null) => void;
}) {
  const { t, tn } = useT();
  const toast = useToast();
  const [edits, setEdits] = useState<Edit[]>(() => initialEdits(proposal));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setEdits(initialEdits(proposal)), [proposal]);

  const set = (i: number, patch: Partial<Edit>) =>
    setEdits((es) => es.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const usable = (it: ProposalItem, e: Edit) =>
    it.action === "cancel"
      ? !!it.session_id && !it.flags.includes("invoiced")
      : !!e.practice_id && DEC.test(e.rate);
  const chosen = proposal.items
    .map((it, i) => ({ it, e: edits[i], i }))
    .filter(({ it, e }) => e?.checked && usable(it, e));
  const adds = chosen.filter((c) => c.it.action === "add").length;
  const cancels = chosen.length - adds;
  const decided = proposal.status !== "pending";

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      const items = chosen.map(({ it, e, i }) => ({
        index: i,
        ...(it.action === "add" && e.practice_id !== it.practice_id ? { practice_id: e.practice_id } : {}),
        ...(it.action === "add" && e.rate !== (it.rate ?? "") ? { rate: e.rate } : {}),
      }));
      const done = await api.post<Proposal>(`/proposals/${proposal.id}/accept`, { items });
      toast({
        text: adds ? tn("booking.added", adds) : tn("booking.cancelled", cancels),
        undo: async () => {
          try {
            await api.post(`/proposals/${proposal.id}/undo`);
            onDone(null);
          } catch {
            /* nothing to undo */
          }
        },
      });
      onDone(done);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const discard = async () => {
    try {
      await api.post(`/proposals/${proposal.id}/reject`);
      onDone(null);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div className="proposal">
      <p className="proposal-source">
        <Icon name={proposal.ai ? "sparkle" : "check"} size={16} />
        {proposal.ai ? t("booking.by_ai") : t("booking.by_rules")}
      </p>
      {proposal.summary && <p className="muted" style={{ marginTop: 0 }}>{proposal.summary}</p>}
      {proposal.questions.length > 0 && (
        <div className="alert info" role="note">
          <strong>{t("booking.questions")}</strong>
          <ul>{proposal.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </div>
      )}
      <ErrorAlert error={error} />
      {proposal.items.length === 0 ? (
        <div className="empty" style={{ padding: "1.25rem 0.5rem" }}>{t("booking.none_found")}</div>
      ) : (
        <ul className="list proposal-items">
          {proposal.items.map((it, i) => {
            const e = edits[i];
            if (!e) return null;
            const ok = usable(it, e);
            const id = `pi-${i}`;
            return (
              <li key={i} className={it.action === "cancel" ? "cancel" : ""}>
                <input id={id} type="checkbox" checked={e.checked && ok} disabled={!ok || decided}
                  onChange={(ev) => set(i, { checked: ev.target.checked })} />
                <span className="list-main">
                  <label htmlFor={id} className="list-title">
                    {weekdayDate(it.date)} · {t(`unit.${it.unit}` as MessageKey)}
                    {it.unit === "hours" && it.hours ? ` (${it.hours})` : ""}
                  </label>
                  <span className="proposal-fields">
                    {it.action === "add" ? (
                      <>
                        <select aria-label={t("booking.practice")} value={e.practice_id ?? ""} disabled={decided}
                          onChange={(ev) => set(i, { practice_id: ev.target.value || null, checked: true })}>
                          <option value="">{it.practice_name ? t("booking.choose_for", { name: it.practice_name }) : t("booking.choose_practice")}</option>
                          {practices.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        <span className="money-input">
                          <span aria-hidden="true">£</span>
                          <input type="text" aria-label={t("booking.rate")} inputMode="decimal" value={e.rate} disabled={decided}
                            placeholder="0.00" onChange={(ev) => set(i, { rate: ev.target.value.trim(), checked: true })} />
                        </span>
                      </>
                    ) : (
                      <span className="list-sub">{it.practice_name ?? ""}</span>
                    )}
                  </span>
                  <span className="row wrap" style={{ gap: "0.3rem", marginTop: "0.3rem" }}>
                    {it.action === "cancel" && <span className="pill overdue">{t("booking.flag_cancel")}</span>}
                    {it.flags.map((f) => (
                      <span key={f} className={`pill ${f === "duplicate" || f === "clash" ? "warn" : "draft"}`}>
                        {t(`booking.flag_${f}` as MessageKey, { practice: it.clash_with ?? "" })}
                      </span>
                    ))}
                    {it.rate_source === "remembered" && e.rate === it.rate && (
                      <span className="pill draft">{t("booking.usual_rate")}</span>
                    )}
                    {it.past && <span className="pill draft">{t("booking.past")}</span>}
                    {it.note && <span className="list-sub">{it.note}</span>}
                  </span>
                </span>
                {it.action === "add" && DEC.test(e.rate) && (
                  <span className="money muted">{gbp(e.rate)}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {!decided && (
        <div className="actions" style={{ marginTop: "1rem" }}>
          <button className="btn" disabled={busy || chosen.length === 0} onClick={accept}>
            {adds > 0 ? tn("booking.add_n", adds) : cancels > 0 ? tn("booking.cancel_n", cancels) : t("booking.add_none")}
          </button>
          <button className="btn ghost" onClick={discard}>{t("booking.discard")}</button>
        </div>
      )}
      <p className="form-foot">{t("booking.you_decide")}</p>
    </div>
  );
}

export function usePractices() {
  const [practices, setPractices] = useState<Practice[]>([]);
  useEffect(() => {
    api.get<Practice[]>("/practices").then(setPractices, () => undefined);
  }, []);
  return practices;
}

export function useAssistant() {
  const [cfg, setCfg] = useState<AssistantConfig | null>(null);
  useEffect(() => {
    api.get<AssistantConfig>("/settings/assistant").then(setCfg, () => undefined);
  }, []);
  return cfg;
}

/** "Paste a booking": paste → read → review → add. Opened from Diary, Today and Inbox. */
export function BookingSheet({
  open,
  onClose,
  onChanged,
  initial,
}: {
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  initial?: Proposal | null;
}) {
  const { t } = useT();
  const practices = usePractices();
  const assistant = useAssistant();
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(initial ?? null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setProposal(initial ?? null);
      setError(null);
    }
  }, [open, initial]);

  const read = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ proposal: Proposal }>("/assistant/booking", { text });
      setProposal(r.proposal);
      setText("");
      onChanged?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const ai = !!assistant?.ready;

  return (
    <Dialog open={open} onClose={onClose} title={proposal ? t("booking.review_title") : t("booking.title")}>
      {proposal ? (
        <ProposalReview proposal={proposal} practices={practices}
          onDone={() => { onChanged?.(); onClose(); }} />
      ) : (
        <>
          <label htmlFor="booking-text" className="sr-only">{t("booking.paste_label")}</label>
          <textarea id="booking-text" rows={9} value={text} autoFocus
            placeholder={t("booking.paste_placeholder")} onChange={(e) => setText(e.target.value)} />
          <p className="form-foot">{ai ? t("booking.hint_ai") : t("booking.hint_rules")}</p>
          <ErrorAlert error={error} />
          <div className="actions">
            <button className="btn" disabled={busy || !text.trim()} onClick={read}>
              {busy ? t("booking.reading") : t("booking.read")}
            </button>
          </div>
        </>
      )}
    </Dialog>
  );
}
