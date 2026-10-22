// Official NHSBSA paper versions of the GP locum Forms A and B, by NHS pension scheme year
// (1 April to 31 March). PCSE prefers PCSE Online; these are for when that isn't possible.
// Only addresses checked against NHSBSA are listed; any other year opens NHSBSA's forms page.

export const PCSE_ONLINE_URL = "https://pcse.england.nhs.uk/services/gp-pensions/locum-gps";
export const NHSBSA_LOCUM_FORMS_URL = "https://www.nhsbsa.nhs.uk/member-hub/information-practitioner-locum-and-non-gp";

const FORMS: Record<number, { a?: string; b?: string }> = {
  2025: {
    a: "https://nhsbsa.nhs.uk/sites/default/files/2025-07/NHS%20Pensions%20-%20GP%20Locum%20A%201%20April%202025%20to%2031%20March%202026%20-%2020250710%20-%20%28V2%29.pdf",
    b: "https://cms.nhsbsa.nhs.uk/sites/default/files/2025-09/NHS%20Pensions%20-%20GP%20locum%20B%201%20April%202025%20to%2031%20March%202026%20-%2020250923%20-%20%28V3%29.pdf",
  },
  2026: {
    a: "https://www.nhsbsa.nhs.uk/sites/default/files/2026-03/NHS%20Pensions%20-%20GP%20Locum%20A%201%20April%202026%20to%2031%20March%202027%20-%2020260226-%20%28V1%29%20.pdf",
  },
};

/** The scheme year a month ("2026-10") falls in, as its starting year: April 2026 – March 2027 → 2026. */
export function schemeYear(month: string): number {
  const [y, m] = month.split("-").map(Number);
  return m >= 4 ? y : y - 1;
}

/** "2026–27" */
export function schemeYearLabel(start: number): string {
  return `${start}–${String((start + 1) % 100).padStart(2, "0")}`;
}

/** Links for one month's forms: the checked PDF when there is one, else NHSBSA's forms page. */
export function paperForms(month: string): { year: string; a: string; b: string; aIsPdf: boolean; bIsPdf: boolean } {
  const start = schemeYear(month);
  const f = FORMS[start] ?? {};
  return {
    year: schemeYearLabel(start),
    a: f.a ?? NHSBSA_LOCUM_FORMS_URL,
    b: f.b ?? NHSBSA_LOCUM_FORMS_URL,
    aIsPdf: !!f.a,
    bIsPdf: !!f.b,
  };
}
