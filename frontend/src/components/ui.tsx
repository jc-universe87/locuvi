import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { hasKey, useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { ApiError } from "../lib/api";
import { ukDate } from "../lib/format";
import type { ArchiveStatus, InvoiceStatus, Issue, PaymentState } from "../lib/types";

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="15" fill="#294D63" />
      <path d="M19 12V44Q19 48 24 48H49" stroke="white" strokeWidth="7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M30 30L38 38L52 22" stroke="#8AC4BF" strokeWidth="5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS: Record<string, string> = {
  today: "M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z",
  diary: "M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  invoices: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5M9 13h6M9 17h6",
  pension: "M12 3 4 7v2h16V7zM6 11v6M10 11v6M14 11v6M18 11v6M4 20h16",
  reports: "M5 20V10M10 20V4M15 20v-7M20 20v-4",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13a7.6 7.6 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.4 7.4 0 0 0-1.7-1L15 3.5h-4l-.4 2.5a7.4 7.4 0 0 0-1.7 1l-2.4-1-2 3.4L6.6 11a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.4 2.4-1c.5.4 1.1.8 1.7 1l.4 2.5h4l.4-2.5c.6-.2 1.2-.6 1.7-1l2.4 1 2-3.4z",
  plus: "M12 5v14M5 12h14",
  chevron: "M9 6l6 6-6 6",
  back: "M15 6l-6 6 6 6",
  close: "M6 6l12 12M18 6 6 18",
  check: "M5 12.5 10 17l9-10",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  send: "M4 12 20 4l-6 16-3-7z",
  money: "M3 7h18v10H3zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  copy: "M8 8h11v12H8zM5 16V4h11",
  alert: "M12 8v5M12 16.5v.5M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z",
  cloud: "M7 18a4 4 0 0 1-.5-8 5.5 5.5 0 0 1 10.6 1.5A3.3 3.3 0 0 1 17 18z",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  inbox: "M4 13h4l1.5 3h5l1.5-3h4M6 5h12l2 8v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6z",
  sparkle: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  paste: "M9 3h6v4H9zM7 5H5v16h14V5h-2M9 12h6M9 16h4",
  upload: "M12 20V9M7 14l5-5 5 5M5 4h14",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
};

export function Icon({ name, size = 22 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={ICONS[name] ?? ""} />
    </svg>
  );
}

/** One pill that tells the whole story: Draft · Due 19 Nov · Overdue 3 days · Paid · Void. */
export function InvoicePill({ status, payment, due }: { status: InvoiceStatus; payment?: PaymentState; due?: string | null }) {
  const { t } = useT();
  if (status === "draft") return <span className="pill draft">{t("status.draft")}</span>;
  if (status === "voided") return <span className="pill voided">{t("status.voided")}</span>;
  const st = payment?.state ?? "unpaid";
  if (st === "paid") return <span className="pill paid">✓ {t("pay.paid")}</span>;
  if (st === "refund_due") return <span className="pill overdue">{t("refund.pill")}</span>;
  if (st === "credited") return <span className="pill voided" style={{ textDecoration: "none" }}>{t("credit.credited")}</span>;
  if (st === "overdue")
    return <span className="pill overdue">{t("pay.overdue_days", { n: payment?.days_overdue ?? 0 })}</span>;
  if (st === "part_paid") return <span className="pill part_paid">{t("pay.part_paid")}</span>;
  return <span className="pill due">{due ? t("pay.due_on", { date: ukDate(due) }) : t("status.issued")}</span>;
}

export function ArchivePill({ archive }: { archive: ArchiveStatus }) {
  const { t } = useT();
  if (!archive.webdav_enabled && archive.status !== "synced") return null;
  if (archive.status === "not_configured") return null;
  return (
    <span className={`pill ${archive.status}`}>
      {archive.status === "synced" && "✓ "}
      {t(`archive.${archive.status}` as MessageKey)}
    </span>
  );
}

function issueText(t: ReturnType<typeof useT>["t"], issue: Issue): string {
  const key = `error.${issue.code}`;
  if (!hasKey(key)) return issue.message;
  const params: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(issue.params ?? {})) {
    if (Array.isArray(v)) params[k] = v.join(", ");
    else if (typeof v === "number") params[k] = k === "line" ? v + 1 : v;
    else if (typeof v === "string") params[k] = v;
  }
  return t(key as MessageKey, params);
}

export function useIssueText() {
  const { t } = useT();
  return (issue: Issue) => issueText(t, issue);
}

export function errorText(t: ReturnType<typeof useT>["t"], err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return t("error.network");
    return issueText(t, err.body as Issue);
  }
  return t("error.generic");
}

export function ErrorAlert({ error }: { error: unknown }) {
  const { t } = useT();
  const fmt = useIssueText();
  if (!error) return null;
  const problems =
    error instanceof ApiError && Array.isArray(error.body.params?.problems)
      ? (error.body.params.problems as Issue[])
      : null;
  return (
    <div className="alert error" role="alert">
      {errorText(t, error)}
      {problems && (
        <ul>
          {problems.map((p, i) => (
            <li key={i}>{fmt(p)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Modal sheet: bottom sheet on phones, centred card on larger screens. */
export function Dialog({
  open,
  title,
  children,
  footer,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
}) {
  const { t } = useT();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    } else if (!open && d.open) {
      if (typeof d.close === "function") d.close();
      else d.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="sheet"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="sheet-title"
    >
      {open && (
        <>
          <div className="sheet-head">
            <h2 id="sheet-title">{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label={t("common.close")}>
              <Icon name="close" />
            </button>
          </div>
          <div className="sheet-body">{children}</div>
          {footer && <div className="sheet-foot">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

export function Field({
  id,
  label,
  hint,
  optional,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  optional?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const { t } = useT();
  return (
    <div className={`field ${className ?? ""}`}>
      <label htmlFor={id}>
        {label}
        {optional && <span className="faint"> · {t("common.optional")}</span>}
      </label>
      {children}
      {hint && (
        <span className="hint" id={`${id}-hint`}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function Toggle({ id, checked, onChange, label }: { id?: string; checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <span className="switch">
      <input id={id} type="checkbox" role="switch" checked={checked} aria-label={label} onChange={(e) => onChange(e.target.checked)} />
      <span aria-hidden="true" />
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- toast */

interface ToastMsg {
  text: string;
  undo?: () => void;
}
const ToastCtx = createContext<(m: ToastMsg) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useT();
  const [msg, setMsg] = useState<ToastMsg | null>(null);
  const timer = useRef<number>();
  const show = useCallback((m: ToastMsg) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(null), m.undo ? 6000 : 3000);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <div className="toast" role="status" aria-live="polite">
          <span>{msg.text}</span>
          {msg.undo && (
            <button
              className="btn small"
              onClick={() => {
                msg.undo?.();
                setMsg(null);
              }}
            >
              {t("common.undo")}
            </button>
          )}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

/* ---------------------------------------------------------------- autosave */

/** Debounced autosave. Returns a "Saved" flag that briefly shows after each save. */
export function useAutosave<T>(value: T, save: (v: T) => Promise<void>, { delay = 600, enabled = true } = {}) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<unknown>(null);
  const first = useRef(true);
  const latest = useRef(save);
  latest.current = save;
  const json = JSON.stringify(value);
  useEffect(() => {
    if (!enabled) return;
    if (first.current) {
      first.current = false;
      return;
    }
    const h = window.setTimeout(async () => {
      setState("saving");
      try {
        await latest.current(JSON.parse(json) as T);
        setError(null);
        setState("saved");
        window.setTimeout(() => setState((s) => (s === "saved" ? "idle" : s)), 1800);
      } catch (e) {
        setError(e);
        setState("error");
      }
    }, delay);
    return () => window.clearTimeout(h);
  }, [json, delay, enabled]);
  return { state, error };
}

export function SavedIndicator({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  const { t } = useT();
  return (
    <span className={`saved ${state === "saved" || state === "saving" ? "" : "hidden"}`} role="status" aria-live="polite">
      {state === "saving" ? t("common.saving") : state === "saved" ? `✓ ${t("common.saved")}` : ""}
    </span>
  );
}

export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="row wrap" style={{ marginBottom: "0.5rem" }}>
      <h1 style={{ margin: "0.25rem 0 0.75rem" }}>{title}</h1>
      <span className="spacer" />
      {children}
    </div>
  );
}
