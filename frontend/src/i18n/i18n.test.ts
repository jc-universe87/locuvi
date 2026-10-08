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
