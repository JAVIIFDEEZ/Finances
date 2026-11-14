/**
 * Presentation helpers of the price patterns (ADR-0035): families in order, the latest
 * events and the markers of one pattern on the price chart.
 */

import type { Schemas } from "@/lib/api/client";

export type Pattern = Schemas["PatternOut"];
export type PatternEvent = Schemas["PatternEventOut"];
export type Family = Pattern["family"];
export type Direction = Pattern["direction"];

/** Families in the order the panel shows them. */
export const FAMILIES: readonly Family[] = ["candle", "liquidity", "session", "zone"];

/** The patterns of each family, keeping their order; families without patterns left out. */
export function byFamily(patterns: readonly Pattern[]): { family: Family; patterns: Pattern[] }[] {
  return FAMILIES.map((family) => ({ family, patterns: patterns.filter((p) => p.family === family) })).filter(
    (group) => group.patterns.length > 0,
  );
}

/** The ``count`` most recent events, newest first (events come oldest first). */
export function recentEvents(events: readonly PatternEvent[], count: number): PatternEvent[] {
  return events.slice(Math.max(0, events.length - count)).reverse();
}

/** The occurrences of one pattern, each with the direction its definition points to. */
export function occurrences(
  events: readonly PatternEvent[],
  pattern: Pattern | undefined,
): { time: string; direction: Direction }[] {
  if (!pattern) return [];
  return events.filter((e) => e.name === pattern.name).map((e) => ({ time: String(e.time), direction: pattern.direction }));
}
