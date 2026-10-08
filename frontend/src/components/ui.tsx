import { useEffect, useRef, type ReactNode } from "react";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n/en";
import { hasKey } from "../i18n";
import { ApiError } from "../lib/api";
import type { ArchiveStatus, InvoiceStatus, Issue } from "../lib/types";

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="13" fill="#294D63" />
      <path d="M19 12V44Q19 48 24 48H49" stroke="white" strokeWidth="7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M30 30L38 38L52 22" stroke="#8AC4BF" strokeWidth="5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const { t } = useT();
  return <span className={`badge ${status}`}>{t(`status.${status}` as MessageKey)}</span>;
}

export function ArchiveBadge({ archive, compact }: { archive: ArchiveStatus; compact?: boolean }) {
  const { t } = useT();
  if (archive.status === "not_configured" || (!archive.webdav_enabled && archive.status !== "synced")) {
    return compact ? <span className="muted">{t("archive.not_configured")}</span> : null;
  }
  return (
    <span className={`badge ${archive.status}`}>
      {archive.status === "synced" && <span className="tick" aria-hidden="true">✓</span>}
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
  footer: ReactNode;
  onClose: () => void;
}) {
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
    <dialog ref={ref} onCancel={(e) => { e.preventDefault(); onClose(); }} aria-labelledby="dialog-title">
      {open && (
        <>
          <div className="dialog-body">
            <h2 id="dialog-title">{title}</h2>
            {children}
          </div>
          <div className="dialog-foot">{footer}</div>
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
        {optional && <span className="hint"> ({t("common.optional")})</span>}
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
