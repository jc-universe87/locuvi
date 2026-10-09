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

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** ISO yyyy-mm-dd → "8 Oct 2026" (UK order, no timezone shifting). */
export function ukDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function period(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  if (!end || end === start) return ukDate(start);
  return `${ukDate(start)} – ${ukDate(end)}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { timeZone: "Europe/London", dateStyle: "medium", timeStyle: "short" });
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

const LONG_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "2026-10" → "October 2026" */
export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return `${LONG_MONTHS[m - 1]} ${y}`;
}

/** "2026-10" → "Oct" */
export function monthShort(ym: string): string {
  return MONTHS[Number(ym.split("-")[1]) - 1];
}

/** Whole pounds for headline numbers: "1411.78" → "£1,412" */
export function gbpRound(value: string | null | undefined): string {
  if (!value) return "£0";
  const n = Math.round(Number(value));
  return `${n < 0 ? "-" : ""}£${Math.abs(n).toLocaleString("en-GB")}`;
}

export function weekdayDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  return `${wd} ${d} ${MONTHS[m - 1]}`;
}
