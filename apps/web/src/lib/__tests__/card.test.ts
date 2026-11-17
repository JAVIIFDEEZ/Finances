import { describe, expect, it } from "vitest";

import { formatter } from "@/lib/i18n/format";
import { codeKey, factOf, factText, listedFacts, meterFill, scoreDirection, type Fact, type Pillar } from "@/lib/util/card";

const fmt = formatter("en");
const none = () => null;

const technical: Pillar = {
  pillar: "technical",
  directional: true,
  score: 0.35,
  issue: null,
  facts: [
    { key: "verdict", value: "aligned_bullish", unit: "code" },
    { key: "alignment", value: 0.35, unit: "number" },
    { key: "trend", value: "up", unit: "code" },
    { key: "price_vs_average", value: 0.048, unit: "ratio" },
    { key: "frames_read", value: 3, unit: "count" },
  ],
};

describe("listedFacts", () => {
  it("leaves the headline of the technical pillar out of its list", () => {
    expect(listedFacts(technical).map((fact) => fact.key)).toEqual(["trend", "price_vs_average", "frames_read"]);
  });

  it("lists every fact of a pillar without a headline", () => {
    const risk: Pillar = { pillar: "risk", directional: false, score: null, issue: null, facts: [{ key: "volatility", value: 0.31, unit: "ratio" }] };
    expect(listedFacts(risk)).toEqual(risk.facts);
    expect(factOf(risk, "volatility")?.value).toBe(0.31);
    expect(factOf(risk, "nope")).toBeUndefined();
  });
});

describe("factText", () => {
  const text = (fact: Fact, words: (key: string) => string | null = none) => factText(fact, fmt, words);

  it("signs the moves and leaves the sizes unsigned", () => {
    expect(text({ key: "price_vs_average", value: 0.048, unit: "ratio" })).toBe("+4.8%");
    expect(text({ key: "support_distance", value: -0.003, unit: "ratio" })).toBe("-0.3%");
    expect(text({ key: "volatility", value: 0.311, unit: "ratio" })).toBe("31.1%");
    expect(text({ key: "max_drawdown", value: -0.389, unit: "ratio" })).toBe("-38.9%");
  });

  it("formats counts, numbers and dates", () => {
    expect(text({ key: "observations", value: 785, unit: "count" })).toBe("785");
    expect(text({ key: "alignment", value: 0.348, unit: "number" })).toBe("0.35");
    expect(text({ key: "since", value: "2023-11-14", unit: "date" })).toContain("Nov");
  });

  it("words a code it knows and shows as it comes one it does not", () => {
    const words = (key: string) => (key === "trend.up" ? "Upward" : null);
    expect(text({ key: "trend", value: "up", unit: "code" }, words)).toBe("Upward");
    expect(text({ key: "trend", value: "parabolic", unit: "code" }, words)).toBe("parabolic");
    expect(codeKey("verdict", "mixed")).toBe("confluence.verdict.mixed");
    expect(codeKey("worst", "warning")).toBe("markets.severity.warning");
    expect(codeKey("new_fact", "x")).toBe("card.code.new_fact.x");
  });

  it("never prints what could not be told", () => {
    expect(text({ key: "coverage", value: null, unit: "ratio" })).toBe("—");
    expect(text({ key: "volatility", value: Number.NaN, unit: "ratio" })).toBe("—");
  });
});

describe("scoreDirection", () => {
  it("points up, down or nowhere", () => {
    expect(scoreDirection(0.35)).toBe("up");
    expect(scoreDirection(-0.1)).toBe("down");
    expect(scoreDirection(0)).toBe("flat");
    expect(scoreDirection(null)).toBe("flat");
  });
});

describe("meterFill", () => {
  it("grows from the middle towards the side of the score", () => {
    expect(meterFill(0.5)).toEqual({ left: 50, width: 25 });
    expect(meterFill(-0.5)).toEqual({ left: 25, width: 25 });
    expect(meterFill(0)).toEqual({ left: 50, width: 0 });
  });

  it("stays on its track", () => {
    expect(meterFill(3)).toEqual({ left: 50, width: 50 });
    expect(meterFill(-3)).toEqual({ left: 0, width: 50 });
    expect(meterFill(null)).toEqual({ left: 50, width: 0 });
    expect(meterFill(Number.NaN)).toEqual({ left: 50, width: 0 });
  });
});
