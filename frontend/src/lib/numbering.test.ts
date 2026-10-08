import { suggestYearPrefix } from "./numbering";

describe("suggestYearPrefix", () => {
  it("suggests the new year only when the prefix has an older year", () => {
    expect(suggestYearPrefix("LOC-2026-", 2027)).toBe("LOC-2027-");
    expect(suggestYearPrefix("INV2026/", 2027)).toBe("INV2027/");
    expect(suggestYearPrefix("LOC-2027-", 2027)).toBeNull();
    expect(suggestYearPrefix("LOC-", 2027)).toBeNull();
    expect(suggestYearPrefix("LOC-2028-", 2027)).toBeNull();
  });
});
