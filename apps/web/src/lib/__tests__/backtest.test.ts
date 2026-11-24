import { describe, expect, it } from "vitest";

import { backtestRequest, costLines, costShare, excessReturn } from "@/lib/util/backtest";

const costs = { commission: 30, tax: 12, slippage: 8, funding: -40, borrow: 0, total: 10 };

describe("backtest", () => {
  it("compares the strategy with holding the instrument", () => {
    expect(excessReturn({ total_return: 0.06, buy_and_hold: -0.27 })).toBeCloseTo(0.33);
  });

  it("weighs the costs against the capital", () => {
    expect(costShare({ costs, initial_capital: 10_000 })).toBeCloseTo(0.001);
    expect(costShare({ costs, initial_capital: 0 })).toBeNull();
  });

  it("lists what was paid or earned, largest first, and leaves out what was not", () => {
    expect(costLines(costs).map((line) => line.kind)).toEqual(["funding", "commission", "tax", "slippage"]);
  });

  it("leaves the optional figures out of the request, so the profile's apply", () => {
    const form = { symbol: " san.mc ", strategy: "sma_crossover" as const, start: "", end: "2026-01-31", profile: "", commission: "", initialCapital: 10_000 };

    expect(backtestRequest(form)).toEqual({
      symbol: "SAN.MC",
      strategy: "sma_crossover",
      start: null,
      end: "2026-01-31",
      profile: null,
      commission_bps: null,
      initial_capital: 10_000,
    });
    expect(backtestRequest({ ...form, commission: "5", profile: "XMAD" })).toMatchObject({ commission_bps: 5, profile: "XMAD" });
    expect(backtestRequest({ ...form, commission: "abc" }).commission_bps).toBeNull();
  });
});
