import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAssistant } from "../components/Booking";
import { ErrorAlert, Icon, PageHead, useToast } from "../components/ui";
import { hasKey, useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { api } from "../lib/api";

interface Step { tool: string; ok: boolean }
interface Created {
  type: "invoice_draft" | "email_draft";
  invoice_id: string;
  practice?: string | null;
  month?: string;
  kind?: string;
  to?: string | null;
  subject?: string;
  body?: string;
}
interface Turn { role: "user" | "assistant"; text: string; steps?: Step[]; created?: Created[] }
interface AskResult { conversation_id: string; answer: string; steps: Step[]; created: Created[] }

const SUGGESTIONS: MessageKey[] = ["ask.s_check", "ask.s_owed", "ask.s_earned", "ask.s_prepare", "ask.s_pension"];

/** Ask Locuvi: the administrative assistant, answering from your records with its tools. */
export default function AskPage() {
  const { t } = useT();
  const assistant = useAssistant();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conv, setConv] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }), [turns, busy]);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setTurns((ts) => [...ts, { role: "user", text }]);
    setQ("");
    try {
      const r = await api.post<AskResult>("/assistant/ask", { question: text, conversation_id: conv });
      setConv(r.conversation_id);
      setTurns((ts) => [...ts, { role: "assistant", text: r.answer, steps: r.steps, created: r.created }]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (assistant && !assistant.ready) {
    return (
      <>
        <PageHead title={t("ask.title")} />
        <div className="card empty">
          <div className="big" aria-hidden="true">✨</div>
          <p>{t("ask.off")}</p>
          <Link to="/settings/assistant" className="btn">{t("ask.turn_on")}</Link>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHead title={t("ask.title")}>
        {turns.length > 0 && (
          <button className="btn ghost small" onClick={() => { setTurns([]); setConv(null); }}>{t("ask.new")}</button>
        )}
      </PageHead>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>{t("ask.lead")}</p>
      {turns.length === 0 && (
        <div className="chips" style={{ marginBottom: "1rem" }}>
          {SUGGESTIONS.map((k) => (
            <button key={k} className="chip" onClick={() => void ask(t(k))}>{t(k)}</button>
          ))}
        </div>
      )}
      <div className="chat">
        {turns.map((turn, i) => (
          <div key={i} className={`bubble ${turn.role}`}>
            {turn.role === "assistant" && (
              <span className="proposal-source"><Icon name="sparkle" size={14} /> {t("ask.ai_label")}</span>
            )}
            <Answer text={turn.text} />
            {turn.steps && turn.steps.length > 0 && (
              <p className="hint" style={{ margin: "0.4rem 0 0" }}>
                {t("ask.looked_at")}{" "}
                {[...new Set(turn.steps.map((s) => s.tool))].map((n) =>
                  hasKey(`ask.tool_${n}`) ? t(`ask.tool_${n}` as MessageKey) : n).join(", ")}
              </p>
            )}
            {turn.created?.map((c, j) => <CreatedCard key={j} c={c} />)}
          </div>
        ))}
        {busy && <div className="bubble assistant muted">{t("ask.thinking")}</div>}
        <div ref={end} />
      </div>
      <ErrorAlert error={error} />
      <form className="ask-bar" onSubmit={(e) => { e.preventDefault(); void ask(q); }}>
        <label htmlFor="ask-q" className="sr-only">{t("ask.placeholder")}</label>
        <textarea id="ask-q" rows={2} value={q} placeholder={t("ask.placeholder")} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(q); } }} />
        <button className="btn" type="submit" disabled={busy || !q.trim()}>{t("ask.send")}</button>
      </form>
      <p className="form-foot">{t("ask.foot")}</p>
    </>
  );
}

/** Plain text with paragraphs and "- " bullets; no HTML from the model is ever rendered. */
function Answer({ text }: { text: string }) {
  const out: JSX.Element[] = [];
  let para: string[] = [];
  let list: string[] = [];
  const clean = (s: string) => s.replace(/\*\*/g, "");
  const flush = () => {
    if (para.length) out.push(<p key={out.length}>{clean(para.join("\n"))}</p>);
    if (list.length) out.push(<ul key={out.length}>{list.map((l, j) => <li key={j}>{clean(l)}</li>)}</ul>);
    para = [];
    list = [];
  };
  for (const line of text.split("\n")) {
    const bullet = line.match(/^\s*(?:[-•*]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      if (para.length) { const l = list; list = []; flush(); list = l; }
      list.push(bullet[1]);
    } else if (!line.trim()) {
      flush();
    } else {
      if (list.length) flush();
      para.push(line);
    }
  }
  flush();
  return <>{out}</>;
}

function CreatedCard({ c }: { c: Created }) {
  const { t } = useT();
  const toast = useToast();
  if (c.type === "invoice_draft") {
    return (
      <Link to={`/invoices/${c.invoice_id}/edit`} className="created-card">
        <Icon name="invoices" size={18} />
        <span>{t("ask.draft_ready", { practice: c.practice ?? "", month: c.month ?? "" })}</span>
        <Icon name="chevron" size={16} />
      </Link>
    );
  }
  return (
    <div className="created-card column">
      <strong>{t("ask.email_draft", { subject: c.subject ?? "" })}</strong>
      <pre className="doc-text" style={{ margin: "0.4rem 0" }}>{c.body}</pre>
      <span className="actions">
        <button className="btn small secondary" onClick={() => {
          void navigator.clipboard?.writeText(c.body ?? "").then(() => toast({ text: t("ask.copied") }), () => undefined);
        }}>{t("ask.copy")}</button>
        <Link className="btn small" to={`/invoices/${c.invoice_id}`}>{t("ask.open_to_send")}</Link>
      </span>
    </div>
  );
}
