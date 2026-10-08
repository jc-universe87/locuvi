/**
 * If the prefix contains a year (e.g. "LOC-2026-") that is not the current year,
 * suggest the same prefix with the current year. Never applied automatically.
 */
export function suggestYearPrefix(prefix: string, currentYear: number): string | null {
  const m = prefix.match(/(19|20)\d{2}/);
  if (!m) return null;
  const year = Number(m[0]);
  if (year >= currentYear) return null;
  return prefix.replace(m[0], String(currentYear));
}
