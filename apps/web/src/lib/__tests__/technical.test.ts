import { describe, expect, it } from "vitest";

import {
  availableCharts,
  availableOverlays,
  byIndicatorFamily,
  groupUnavailable,
  indicatorLabel,
  pair,
  readingKey,
  readingSide,
  type Indicator,
} from "@/lib/util/technical";

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

describe("readings", () => {
  it("words a reading by what the indicator measures", () => {
    expect(readingKey("RSI", "high")).toBe("reading.zone.high");
    expect(readingKey("ADX", "high")).toBe("reading.trend.high");
    expect(readingKey("CMF", "low")).toBe("reading.pressure.low");
    expect(readingKey("ATR_PCT", "high")).toBe("reading.relative.high");
    expect(readingKey("SMA", "above")).toBe("reading.level.above");
    expect(readingKey("MACD_LINE", "below")).toBe("reading.sign.below");
    expect(readingKey("TRIX", "neutral")).toBe("reading.sign.neutral");
  });

  it("points a reading up, down or neither", () => {
    expect(readingSide("RSI", "high")).toBe("up");
    expect(readingSide("RSI", "low")).toBe("down");
    expect(readingSide("ADX", "high")).toBe("flat"); // a trend, either way
    expect(readingSide("SMA", "below")).toBe("down");
  });

  it("offers the overlays whose lines the series has", () => {
    expect(availableOverlays(["SMA", "EMA", "BB_UPPER", "BB_LOWER", "PSAR"])).toEqual(["averages", "bollinger", "sar"]);
    expect(availableOverlays(["SMA"])).toEqual([]);
  });

  it("groups the indicators by family, without the price", () => {
    const at = (name: string, family: Indicator["family"]): Indicator => ({
      name,
      family,
      kind: "level",
      parameters: {},
      threshold: null,
      latest: 1,
      values: [],
      zone: null,
      reading: null,
      percentile: null,
    });
    const groups = byIndicatorFamily([at("RSI", "momentum"), at("PRICE", "price"), at("SMA", "trend"), at("MFI", "volume")]);
    expect(groups.map((g) => g.family)).toEqual(["trend", "momentum", "volume"]);
  });
});

describe("pair", () => {
  it("takes a zone only as a pair", () => {
    expect(pair([30, 70])).toEqual([30, 70]);
    expect(pair(null)).toBeNull();
    expect(pair([1])).toBeNull();
    expect(pair([1, 2, 3])).toBeNull();
  });
});
