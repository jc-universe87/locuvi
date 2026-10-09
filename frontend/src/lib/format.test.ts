import { addDays, gbp, pct, period, ukDate, monthLabel, monthShort, weekdayDate } from "./format";

describe("format", () => {
  it("formats GBP strings exactly", () => {
    expect(gbp("677.65")).toBe("£677.65");
    expect(gbp("1411.78")).toBe("£1,411.78");
    expect(gbp("1234567.5")).toBe("£1,234,567.50");
    expect(gbp("0")).toBe("£0.00");
    expect(gbp("-5.00")).toBe("-£5.00");
    expect(gbp(null)).toBe("—");
  });
  it("formats percentages without float noise", () => {
    expect(pct("0.1438")).toBe("14.38%");
    expect(pct("0.90")).toBe("90%");
    expect(pct("0.15")).toBe("15%");
  });
  it("formats date labels in the chosen language", () => {
    const original = document.documentElement.lang;
    try {
      document.documentElement.lang = "de";
      expect(monthLabel("2026-10")).toContain("Oktober");
      expect(monthShort("2026-10")).toMatch(/Okt/);
      expect(ukDate("2026-10-08")).toContain("Okt");
      document.documentElement.lang = "ko";
      expect(ukDate("2026-10-08")).toContain("10월");
      expect(monthLabel("2026-10")).toContain("10월");
      expect(weekdayDate("2026-10-08")).toContain("10");
    } finally {
      document.documentElement.lang = original;
    }
  });
  it("formats UK dates without timezone shifts", () => {
    const original = document.documentElement.lang;
    document.documentElement.lang = "en-GB";
    try {
    expect(ukDate("2026-10-08")).toBe("8 Oct 2026");
    expect(period("2026-10-08", "2026-10-15")).toBe("8 Oct 2026 – 15 Oct 2026");
    expect(period("2026-10-08", "2026-10-08")).toBe("8 Oct 2026");
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-03-28", 1)).toBe("2026-03-29"); // across BST change
    } finally { document.documentElement.lang = original; }
  });
});
