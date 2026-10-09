import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { catalogues, translate } from "./index";
import en from "./en";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx?$/.test(f) && !f.endsWith(".test.ts") && !f.endsWith(".test.tsx") ? [p] : [];
  });
}

describe("i18n catalogues", () => {
  it("every literal t() key used in the UI exists in English", () => {
    const missing: string[] = [];
    for (const file of sources(join(__dirname, ".."))) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/\bt\(\s*"([a-z_]+\.[a-z0-9_.]+)"/g)) {
        if (!(m[1] in en)) missing.push(`${file}: ${m[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("dynamic key families used in the UI are complete", () => {
    for (const u of ["am", "pm", "day", "hours", "custom"]) {
      expect(en).toHaveProperty(`unit.${u}`);
      expect(en).toHaveProperty(`editor.default_desc_${u}`);
    }
    for (const s of ["draft", "issued", "voided"]) expect(en).toHaveProperty(`status.${s}`);
    for (const s of ["pending", "uploading", "synced", "failed", "conflict", "not_configured"])
      expect(en).toHaveProperty(`archive.${s}`);
    for (const s of ["you", "bank", "practices", "invoicing", "pension", "email", "storage", "calendar", "mailbox", "assistant", "agents", "password"]) {
      expect(en).toHaveProperty(`settings.s_${s}`);
      expect(en).toHaveProperty(`settings.s_${s}_sub`);
    }
    for (const d of ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]) expect(en).toHaveProperty(`diary.wd_${d}`);
    for (const m of ["bank_transfer", "cheque", "cash", "other"]) expect(en).toHaveProperty(`pay.method_${m}`);
    for (const g of ["morning", "afternoon", "evening"]) expect(en).toHaveProperty(`today.${g}`);
    // Every finding kind the backend checks engine can emit (backend/locuvi/services/checks.py)
    for (const k of ["uninvoiced_month", "uninvoiced_current", "draft_stale", "po_missing", "invoice_overdue",
      "invoice_due_soon", "invoice_awaiting", "session_duplicate", "session_overlap", "pension_due", "pension_overdue", "pension_deadline_not_invoiced", "pension_deadline_unpaid", "pension_deadline_form_a", "pension_deadline_form_b", "pension_deadline_passed",
      "pension_changed", "pension_tier_missing", "practice_no_address", "archive_failed", "archive_conflict",
      "backup_never", "backup_stale", "proposals_pending", "inbox_waiting", "mailbox_failed", "bank_unmatched", "form_a_chase", "pcse_mismatch"]) expect(en).toHaveProperty(`finding.${k}`);
    for (const f of ["needs_practice", "needs_rate", "duplicate", "rate_differs", "clash", "not_in_diary", "invoiced", "cancel"])
      expect(en).toHaveProperty(`booking.flag_${f}`);
    for (const k of ["booking", "remittance", "statement", "pension", "other"]) expect(en).toHaveProperty(`inbox.kind_${k}`);
    for (const k of ["number", "amount_practice", "amount", "combined"]) expect(en).toHaveProperty(`bank.kind_${k}`);
    for (const s of ["accepted", "partial", "rejected", "verified"]) expect(en).toHaveProperty(`inbox.proposal_${s}`);
  });

  it("other locales only contain known keys with the same placeholders", () => {
    for (const [loc, cat] of Object.entries(catalogues)) {
      for (const [k, v] of Object.entries(cat)) {
        expect(k in en, `${loc}:${k}`).toBe(true);
        const ph = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
        expect(ph(v as string), `${loc}:${k}`).toEqual(ph((en as Record<string, string>)[k]));
      }
    }
  });

  it("falls back to English and interpolates", () => {
    expect(translate("de", "nav.invoices")).toBe("Rechnungen");
    expect(translate("de", "issue.confirm_total", { total: "£1.00" })).toBe("Total: £1.00");
  });
});
