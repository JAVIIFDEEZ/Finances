import { describe, expect, it } from "vitest";

import { fill, isMessageKey } from "@/lib/i18n/messages";
import { byFamily, occurrences, recentEvents, type Pattern, type PatternEvent } from "@/lib/util/patterns";

function pattern(name: string, family: Pattern["family"], direction: Pattern["direction"] = "neutral"): Pattern {
  return { name, family, direction, state: family === "zone", parameters: {}, count: 1, last: null, active: false };
}

const EVENTS: PatternEvent[] = [
  { time: "2026-01-02", name: "BULL_ENGULF" },
  { time: "2026-01-05", name: "CRT" },
  { time: "2026-01-06", name: "BULL_ENGULF" },
  { time: "2026-01-07", name: "FVG_BEAR" },
];

describe("byFamily", () => {
  it("groups patterns by family in the panel's order and leaves empty families out", () => {
    const groups = byFamily([pattern("FIB_DISCOUNT", "zone"), pattern("CRT", "liquidity"), pattern("DOJI", "candle")]);

    expect(groups.map((g) => g.family)).toEqual(["candle", "liquidity", "zone"]);
    expect(groups[1]?.patterns.map((p) => p.name)).toEqual(["CRT"]);
  });
});

describe("recentEvents", () => {
  it("returns the latest events, newest first", () => {
    expect(recentEvents(EVENTS, 2)).toEqual([EVENTS[3], EVENTS[2]]);
    expect(recentEvents(EVENTS, 10)).toHaveLength(4);
    expect(recentEvents([], 3)).toEqual([]);
  });
});

describe("occurrences", () => {
  it("lists one pattern's bars with the direction of its definition", () => {
    expect(occurrences(EVENTS, pattern("BULL_ENGULF", "candle", "bullish"))).toEqual([
      { time: "2026-01-02", direction: "bullish" },
      { time: "2026-01-06", direction: "bullish" },
    ]);
    expect(occurrences(EVENTS, undefined)).toEqual([]);
  });
});

describe("isMessageKey", () => {
  it("knows every pattern name the panel shows, and nothing else", () => {
    expect(isMessageKey("pattern.BULL_ENGULF")).toBe(true);
    expect(isMessageKey("pattern.NOT_YET_IN_THE_WEB")).toBe(false);
    expect(isMessageKey("toString")).toBe(false);
  });
});

describe("fill", () => {
  it("fills in the placeholders it knows and leaves the rest", () => {
    expect(fill("{x} veces la media de {n} velas", { x: "1,3", n: 20 })).toBe("1,3 veces la media de 20 velas");
    expect(fill("hasta {fecha}", {})).toBe("hasta {fecha}");
  });
});
