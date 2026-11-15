import { describe, expect, it } from "vitest";

import { biasSide, byStyle, firstReadable, PRESETS, ruleFigure, scoreSide, signed, type Frame, type Rule } from "@/lib/util/confluence";

const number = (value: number | null | undefined, digits = 2) => (value == null ? "—" : value.toFixed(digits));

function rule(name: string, style: Rule["style"], values: Record<string, number>, bias: Rule["bias"] = "neutral"): Rule {
  return { name, style, bias, values, parameters: {} };
}

function frame(frequency: Frame["frequency"], issue: Frame["issue"]): Frame {
  return {
    frequency,
    issue,
    weight: 1,
    bars: 0,
    last_at: null,
    derived: false,
    score: null,
    verdict: null,
    bullish: 0,
    bearish: 0,
    neutral: 0,
    trend_score: null,
    reversal_score: null,
    trend: null,
    rules: [],
    skipped: [],
  };
}

describe("ruleFigure", () => {
  it("shows what each rule compared, prices with the instrument's decimals", () => {
    expect(ruleFigure(rule("RSI", "reversal", { rsi: 71.234 }), number, 2)).toBe("71.2");
    expect(ruleFigure(rule("MACD", "trend", { macd: -0.31, signal: -0.4 }), number, 2)).toBe("-0.31 / -0.40");
    expect(ruleFigure(rule("SMA_50", "trend", { average: 1.08512, close: 1.09 }), number, 4)).toBe("1.0851");
    expect(ruleFigure(rule("BOLLINGER", "reversal", { lower: 41.18, upper: 44.18 }), number, 2)).toBe("41.18 – 44.18");
    expect(ruleFigure(rule("ADX", "trend", { adx: 27.04, plus_di: 23.1, minus_di: 18.26 }), number, 2)).toBe("27.0 · +DI 23.1 / −DI 18.3");
  });
});

describe("sides", () => {
  it("points a bias and a score up, down or nowhere", () => {
    expect([biasSide("bullish"), biasSide("bearish"), biasSide("neutral")]).toEqual(["up", "down", "flat"]);
    expect([scoreSide(0.4), scoreSide(-0.1), scoreSide(0), scoreSide(null)]).toEqual(["up", "down", "flat", "flat"]);
    expect([signed("0,42", 0.42), signed("-0,10", -0.1), signed("0,00", 0), signed("—", null)]).toEqual(["+0,42", "-0,10", "0,00", "—"]);
  });
});

describe("frames and rules", () => {
  it("picks the first frame that could be read", () => {
    expect(firstReadable([frame("1h", "no_data"), frame("1d", null), frame("1w", null)])?.frequency).toBe("1d");
    expect(firstReadable([frame("1h", "no_data")])).toBeUndefined();
  });

  it("groups the rules by style, trend first", () => {
    const groups = byStyle([rule("RSI", "reversal", {}), rule("MACD", "trend", {}), rule("CCI", "reversal", {})]);
    expect(groups.map((g) => [g.style, g.rules.map((r) => r.name)])).toEqual([
      ["trend", ["MACD"]],
      ["reversal", ["RSI", "CCI"]],
    ]);
    expect(byStyle([rule("RSI", "reversal", {})]).map((g) => g.style)).toEqual(["reversal"]);
  });

  it("offers a positional and an intraday set of frames", () => {
    expect(PRESETS.positional).toEqual(["1d", "1w", "1mo"]);
    expect(PRESETS.intraday).toEqual(["15m", "1h", "4h", "1d"]);
  });
});
