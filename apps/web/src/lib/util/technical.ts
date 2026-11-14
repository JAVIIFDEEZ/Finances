/**
 * Presentation helpers of the technical indicators (ADR-0034): which oscillators can be
 * charted for a series, and how an indicator is named with its parameters.
 */

/** Oscillators offered in the chart, in order; MACD charts its line and signal together. */
export const CHARTS = ["RSI", "MACD", "STOCH", "ADX", "CCI", "MFI"] as const;
export type Chart = (typeof CHARTS)[number];

/** The catalogue names each chart draws. */
export const CHART_LINES: Record<Chart, readonly string[]> = {
  RSI: ["RSI"],
  MACD: ["MACD_LINE", "MACD_SIGNAL"],
  STOCH: ["STOCH"],
  ADX: ["ADX"],
  CCI: ["CCI"],
  MFI: ["MFI"],
};

/** The charts whose lines the series has, in the order of {@link CHARTS}. */
export function availableCharts(names: Iterable<string>): Chart[] {
  const present = new Set(names);
  return CHARTS.filter((chart) => CHART_LINES[chart].every((line) => present.has(line)));
}

/** An indicator with its parameters, e.g. ``RSI (14)`` or ``BB_UPPER (20, 2)``. */
export function indicatorLabel(name: string, parameters: Record<string, number>): string {
  const values = Object.values(parameters);
  return values.length === 0 ? name : `${name} (${values.join(", ")})`;
}

/** What an indicator or a pattern can lack: a price column, or intraday bars. */
export type Column = "open" | "high" | "low" | "close" | "volume" | "intraday";

export interface Unavailable {
  name: string;
  missing: readonly Column[];
}

/** Indicators the series cannot have, grouped by the columns they miss (in their order). */
export function groupUnavailable(items: readonly Unavailable[]): { missing: Column[]; names: string[] }[] {
  const groups = new Map<string, { missing: Column[]; names: string[] }>();
  for (const item of items) {
    const key = item.missing.join(",");
    const group = groups.get(key) ?? { missing: [...item.missing], names: [] };
    group.names.push(item.name);
    groups.set(key, group);
  }
  return [...groups.values()];
}
