/**
 * Backtests (ADR-0050, ADR-0051): what the screen decides from a result, as pure functions.
 */

import type { Schemas } from "@/lib/api/client";

export type Backtest = Schemas["BacktestOut"];
export type BacktestRequest = Schemas["BacktestIn"];
export type CostProfile = Schemas["CostProfileOut"];
export type ClassicName = Exclude<BacktestRequest["strategy"], Schemas["StrategyIn"]>;

/** The classic strategies the screen offers, in the API's order. */
export const CLASSICS: readonly ClassicName[] = [
  "rsi_reversal",
  "macd_crossover",
  "sma_crossover",
  "ema_trend",
  "bollinger_bounce",
  "donchian_breakout",
  "trend_pullback",
];

/** What the strategy earned over holding the instrument, in return points. */
export function excessReturn(data: Pick<Backtest, "total_return" | "buy_and_hold">): number {
  return data.total_return - data.buy_and_hold;
}

/** What trading cost, as a share of the initial capital (``null`` without capital). */
export function costShare(data: Pick<Backtest, "costs" | "initial_capital">): number | null {
  return data.initial_capital > 0 ? data.costs.total / data.initial_capital : null;
}

/** The costs that were paid (or earned: funding can be negative), largest first. */
export function costLines(costs: Backtest["costs"]): { kind: "commission" | "tax" | "slippage" | "funding" | "borrow"; value: number }[] {
  const kinds = ["commission", "tax", "slippage", "funding", "borrow"] as const;
  return kinds
    .map((kind) => ({ kind, value: costs[kind] }))
    .filter((line) => line.value !== 0)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}

/** The request of a form: optional figures left out when empty, so the profile's apply. */
export function backtestRequest(form: {
  symbol: string;
  strategy: ClassicName;
  start: string;
  end: string;
  profile: string;
  commission: string;
  initialCapital: number;
}): BacktestRequest {
  const commission = form.commission.trim() === "" ? null : Number(form.commission);
  return {
    symbol: form.symbol.trim().toUpperCase(),
    strategy: form.strategy,
    start: form.start || null,
    end: form.end || null,
    profile: form.profile || null,
    commission_bps: commission !== null && Number.isFinite(commission) ? commission : null,
    initial_capital: form.initialCapital,
  };
}
