import { describe, expect, it } from "vitest";

import { formatter } from "@/lib/i18n/format";

describe("formatter", () => {
  const es = formatter("es");
  const en = formatter("en");

  it("formats percentages in each locale", () => {
    expect(es.percent(0.0523)).toBe("5,2\u00a0%"); // a non-breaking space, as Spanish typography wants
    expect(en.percent(0.0523)).toBe("5.2%");
    expect(en.signedPercent(0.1)).toBe("+10.0%");
    expect(en.signedPercent(-0.025, 2)).toBe("-2.50%");
  });

  it("never prints NaN: undefined figures are a dash", () => {
    expect(es.percent(Number.NaN)).toBe("—");
    expect(en.number(null)).toBe("—");
    expect(en.money(undefined, "EUR")).toBe("—");
    expect(es.date(null)).toBe("—");
  });

  it("formats money and session dates as calendar dates", () => {
    expect(en.money(12_692.4, "EUR")).toBe("€12,692");
    // A session date is a calendar day, never shifted by the viewer's timezone.
    expect(en.date("2024-03-01")).toContain("Mar");
    expect(en.date("2024-03-01")).toContain("01");
  });
});
