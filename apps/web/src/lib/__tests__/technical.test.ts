import { describe, expect, it } from "vitest";

import { availableCharts, groupUnavailable, indicatorLabel } from "@/lib/util/technical";

describe("availableCharts", () => {
  it("offers only the charts whose lines the series has, in a fixed order", () => {
    expect(availableCharts(["MFI", "RSI", "MACD_LINE", "MACD_SIGNAL", "SMA"])).toEqual(["RSI", "MACD", "MFI"]);
  });

  it("needs both MACD lines to offer the MACD", () => {
    expect(availableCharts(["MACD_LINE"])).toEqual([]);
  });
});

describe("indicatorLabel", () => {
  it("names the indicator with its parameters", () => {
    expect(indicatorLabel("RSI", { window: 14 })).toBe("RSI (14)");
    expect(indicatorLabel("BB_UPPER", { window: 20, dev: 2 })).toBe("BB_UPPER (20, 2)");
    expect(indicatorLabel("PRICE", {})).toBe("PRICE");
  });
});

describe("groupUnavailable", () => {
  it("groups the indicators by the columns they miss, keeping their order", () => {
    expect(
      groupUnavailable([
        { name: "CCI", missing: ["high", "low"] },
        { name: "VOLRATIO", missing: ["volume"] },
        { name: "ADX", missing: ["high", "low"] },
      ]),
    ).toEqual([
      { missing: ["high", "low"], names: ["CCI", "ADX"] },
      { missing: ["volume"], names: ["VOLRATIO"] },
    ]);
  });
});
