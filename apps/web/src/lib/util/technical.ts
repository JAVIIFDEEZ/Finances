/**
 * Presentation helpers of the technical indicators (ADR-0034): which oscillators can be
 * charted for a series, and how an indicator is named with its parameters.
 */

import type { Schemas } from "@/lib/api/client";

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

export type Indicator = Schemas["IndicatorOut"];
export type IndicatorFamily = Indicator["family"];
export type Reading = NonNullable<Indicator["reading"]>;

/** Families in the order the panel shows them (the price itself is not listed). */
export const INDICATOR_FAMILIES: readonly Exclude<IndicatorFamily, "price">[] = ["trend", "momentum", "volatility", "volume"];

/** Lines that can be drawn over the prices, with the indicators each one draws. */
export const OVERLAYS = {
  averages: { lines: ["SMA", "EMA"], style: "solid" },
  bollinger: { lines: ["BB_UPPER", "BB_LOWER"], style: "dashed" },
  keltner: { lines: ["KELT_UPPER", "KELT_LOWER"], style: "dashed" },
  ichimoku: { lines: ["ICHI_CONV", "ICHI_BASE"], style: "solid" },
  sar: { lines: ["PSAR"], style: "dots" },
} as const satisfies Record<string, { lines: readonly string[]; style: "solid" | "dashed" | "dots" }>;
export type Overlay = keyof typeof OVERLAYS;

/** The overlays whose lines the series has. */
export function availableOverlays(names: Iterable<string>): Overlay[] {
  const present = new Set(names);
  return (Object.keys(OVERLAYS) as Overlay[]).filter((overlay) => OVERLAYS[overlay].lines.every((line) => present.has(line)));
}

/** The indicators of each family, keeping their order; families without any left out. */
export function byIndicatorFamily<T extends { family: IndicatorFamily }>(
  indicators: readonly T[],
): { family: Exclude<IndicatorFamily, "price">; indicators: T[] }[] {
  return INDICATOR_FAMILIES.map((family) => ({ family, indicators: indicators.filter((i) => i.family === family) })).filter(
    (group) => group.indicators.length > 0,
  );
}

/** Words for a reading, which depend on what the indicator measures (a high ADX is a trend). */
export function readingKey(
  name: string,
  reading: Reading,
):
  | `reading.zone.${"high" | "low" | "neutral"}`
  | `reading.trend.${"high" | "low" | "neutral"}`
  | `reading.aroon.${"high" | "low" | "neutral"}`
  | `reading.pressure.${"high" | "low" | "neutral"}`
  | `reading.relative.${"high" | "low" | "neutral"}`
  | `reading.sign.${"above" | "below" | "neutral"}`
  | `reading.level.${"above" | "below" | "neutral"}` {
  if (reading === "above" || reading === "below") return LEVEL_LIKE.has(name) ? `reading.level.${reading}` : `reading.sign.${reading}`;
  if (CENTRED.has(name)) return "reading.sign.neutral";
  if (LEVEL_LIKE.has(name)) return "reading.level.neutral";
  if (name === "ADX") return `reading.trend.${reading}`;
  if (name === "AROON") return `reading.aroon.${reading}`;
  if (name === "CMF") return `reading.pressure.${reading}`;
  if (name === "ATR_PCT" || name === "VOLRATIO") return `reading.relative.${reading}`;
  return `reading.zone.${reading}`;
}

/** The side a reading points to, for its mark: up, down or neither. */
export function readingSide(name: string, reading: Reading): "up" | "down" | "flat" {
  if (reading === "above") return "up";
  if (reading === "below") return "down";
  if (reading === "neutral" || name === "ADX" || name === "ATR_PCT" || name === "VOLRATIO") return "flat";
  return reading === "high" ? "up" : "down";
}

const CENTRED = new Set(["ROC", "TRIX", "MACD_LINE", "MACD_SIGNAL"]);
const LEVEL_LIKE = new Set([
  "SMA",
  "EMA",
  "WMA",
  "HMA",
  "KAMA",
  "ICHI_CONV",
  "ICHI_BASE",
  "PSAR",
  "BB_UPPER",
  "BB_LOWER",
  "KELT_UPPER",
  "KELT_LOWER",
  "DONCH_UPPER",
  "DONCH_LOWER",
  "FIB_RETR",
]);

/** A zone as a pair (the API sends ``[low, high]``; anything else is no zone). */
export function pair(values: readonly number[] | null | undefined): readonly [number, number] | null {
  const [low, high, ...rest] = values ?? [];
  return low === undefined || high === undefined || rest.length > 0 ? null : [low, high];
}
