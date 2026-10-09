// Recently deleted: one restore path for the Undo toasts and the Settings list.
import { errorText, type useToast } from "../components/ui";
import type { useT } from "../i18n";
import { api } from "./api";

export type TrashKind = "sessions" | "invoice" | "payment" | "pension_policy" | "pension_submission" | "document" | "mailbox";

export interface TrashItem {
  id: string;
  kind: TrashKind;
  label: string;
  summary: Record<string, string | number | boolean | null>;
  deleted_at: string;
  purge_on: string;
}

export interface RestoreResult {
  kind: TrashKind;
  id?: string | number;
  restored: number;
  skipped: number;
}

type T = ReturnType<typeof useT>;

/** Put something back and say so (or why not). Resolves to null when it couldn't be restored. */
export async function restoreFromBin(id: string, t: T["t"], tn: T["tn"], toast: ReturnType<typeof useToast>): Promise<RestoreResult | null> {
  try {
    const r = await api.post<RestoreResult>(`/trash/${encodeURIComponent(id)}/restore`);
    toast({ text: r.skipped > 0 ? tn("trash.restored_some", r.restored, { skipped: r.skipped }) : t("trash.restored") });
    return r;
  } catch (e) {
    toast({ text: errorText(t, e) });
    return null;
  }
}
