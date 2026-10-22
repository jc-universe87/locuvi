import { NHSBSA_LOCUM_FORMS_URL, paperForms, schemeYear, schemeYearLabel } from "./pensionForms";

describe("pension forms by scheme year", () => {
  it("puts April–March into one scheme year", () => {
    expect(schemeYear("2026-04")).toBe(2026);
    expect(schemeYear("2027-03")).toBe(2026);
    expect(schemeYear("2026-03")).toBe(2025);
    expect(schemeYearLabel(2026)).toBe("2026–27");
    expect(schemeYearLabel(2099)).toBe("2099–00");
  });

  it("links the checked PDF, or NHSBSA's forms page when there isn't one", () => {
    const oct = paperForms("2026-10");
    expect(oct.year).toBe("2026–27");
    expect(oct.aIsPdf && oct.a.endsWith(".pdf")).toBe(true);
    expect(oct.b).toBe(NHSBSA_LOCUM_FORMS_URL); // the 2026–27 Form B isn't listed yet
    const old = paperForms("2025-06");
    expect(old.aIsPdf && old.bIsPdf).toBe(true);
    expect(paperForms("2030-05")).toMatchObject({ a: NHSBSA_LOCUM_FORMS_URL, b: NHSBSA_LOCUM_FORMS_URL, aIsPdf: false });
  });
});
