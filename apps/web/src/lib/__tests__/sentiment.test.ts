import { describe, expect, it } from "vitest";

import { fearGreedBand, isExtreme } from "@/lib/util/sentiment";

describe("fearGreedBand", () => {
  it("follows alternative.me's bands, edges included", () => {
    expect([0, 25, 26, 46, 47, 54, 55, 75, 76, 100].map(fearGreedBand)).toEqual([
      "extremeFear",
      "extremeFear",
      "fear",
      "fear",
      "neutral",
      "neutral",
      "greed",
      "greed",
      "extremeGreed",
      "extremeGreed",
    ]);
  });

  it("has no band without a valid reading", () => {
    for (const value of [null, undefined, Number.NaN, -1, 101]) {
      expect(fearGreedBand(value)).toBeNull();
    }
  });

  it("flags the two extremes", () => {
    expect(isExtreme("extremeFear")).toBe(true);
    expect(isExtreme("extremeGreed")).toBe(true);
    expect(isExtreme("neutral")).toBe(false);
    expect(isExtreme(null)).toBe(false);
  });
});
