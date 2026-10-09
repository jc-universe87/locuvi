// Display helpers. Amounts arrive as exact decimal strings and are only formatted here,
// never used for arithmetic in the browser (the server is authoritative).

export function gbp(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const neg = value.trim().startsWith("-");
  const [intPart, frac = ""] = value.replace("-", "").split(".");
  const pennies = (frac + "00").slice(0, 2);
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}£${grouped || "0"}.${pennies}`;
}

/** Date formatting follows the active interface language; invoice amounts remain GBP. */
function displayLocale(): string {
  const lang = typeof document !== "undefined" ? document.documentElement.lang : "en-GB";
  return lang === "en" || !lang ? "en-GB" : lang;
}
function isoDate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day ? date : null;
}

/** ISO date-only display: no timezone shift, selected interface language. */
export function ukDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = isoDate(iso);
  return d ? new Intl.DateTimeFormat(displayLocale(), { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d) : iso;
}

export function period(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  if (!end || end === start) return ukDate(start);
  return `${ukDate(start)} – ${ukDate(end)}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(displayLocale(), { timeZone: "Europe/London", dateStyle: "medium", timeStyle: "short" });
}

export function pct(fraction: string | null | undefined): string {
  if (!fraction) return "";
  // String-based ×100 to avoid float noise: "0.1438" -> "14.38%"
  const [i, f = ""] = fraction.split(".");
  const padded = (f + "00").split("");
  const whole = String(Number(i) * 100 + Number(padded.slice(0, 2).join("")));
  const rest = padded.slice(2).join("").replace(/0+$/, "");
  return `${whole}${rest ? "." + rest : ""}%`;
}

/** Today in Europe/London as ISO date. */
export function todayLondon(): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

/** Month names in the selected interface language. */
export function monthLabel(ym: string): string {
  const d = isoDate(ym + "-01");
  return d ? new Intl.DateTimeFormat(displayLocale(), { month: "long", year: "numeric", timeZone: "UTC" }).format(d) : ym;
}
export function monthShort(ym: string): string {
  const d = isoDate(ym + "-01");
  return d ? new Intl.DateTimeFormat(displayLocale(), { month: "short", timeZone: "UTC" }).format(d) : ym;
}

/** Whole pounds for headline numbers: "1411.78" → "£1,412" */
export function gbpRound(value: string | null | undefined): string {
  if (!value) return "£0";
  const n = Math.round(Number(value));
  return `${n < 0 ? "-" : ""}£${Math.abs(n).toLocaleString("en-GB")}`;
}

export function weekdayDate(iso: string): string {
  const d = isoDate(iso);
  if (!d) return iso;
  const locale = displayLocale();
  if (locale === "en-GB") {
    const wd = new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: "UTC" }).format(d);
    return `${wd} ${d.getUTCDate()} ${monthShort(iso.slice(0, 7))}`;
  }
  return new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(d);
}
