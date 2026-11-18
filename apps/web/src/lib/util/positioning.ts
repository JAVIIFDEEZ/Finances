/**
 * Presentation helpers of a derivative's positioning (ADR-0042): which window and spacing to
 * ask for, which open interest to draw, and what the change over the window is. The API
 * sends the snapshots each venue publishes; nothing here fills in what a venue does not.
 */

import type { Schemas } from "@/lib/api/client";

export type Positioning = Schemas["PositioningOut"];
export type PositioningColumn = Schemas["PositioningColumnOut"];
export type PositioningField = PositioningColumn["field"];
export type PositioningInterval = Positioning["frequency"];

/** Windows offered, each read at a spacing that keeps a few hundred points at most. */
export const POSITIONING_WINDOWS = ["7d", "30d", "90d"] as const;
export type PositioningWindow = (typeof POSITIONING_WINDOWS)[number];

const WINDOW: Readonly<Record<PositioningWindow, { days: number; interval: "1h" | "4h" | "1d" }>> = {
  "7d": { days: 7, interval: "1h" },
  "30d": { days: 30, interval: "4h" },
  "90d": { days: 90, interval: "1d" },
};

/** The first UTC day and the spacing of a window ending today (positioning days are UTC). */
export function positioningWindow(window: PositioningWindow, today: Date = new Date()): { start: string; interval: "1h" | "4h" | "1d" } {
  const { days, interval } = WINDOW[window];
  const start = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - days));
  return { start: start.toISOString().slice(0, 10), interval };
}

/** Ratios listed with their figures, each with a fixed slot of the palette (colour follows the field). */
export const RATIO_FIELDS: readonly PositioningField[] = ["long_short_accounts", "top_long_short_accounts", "top_long_short_positions", "taker_buy_sell"];

/**
 * Ratios drawn together: how traders stand, which moves slowly around 1. The takers' buy/sell
 * ratio is flow within each period (it jumps to 10 or more) and would flatten them: it is
 * listed, not drawn.
 */
export const CHARTED_RATIOS = ["long_short_accounts", "top_long_short_accounts", "top_long_short_positions"] as const satisfies readonly PositioningField[];

/** Palette slot of each field: never its rank among those a venue publishes. */
export function fieldSlot(field: PositioningField): number {
  return field === "open_interest" || field === "open_interest_value" ? 0 : 1 + RATIO_FIELDS.indexOf(field);
}

/** The column of ``field``, if the venue publishes it. */
export function columnOf(data: Positioning, field: PositioningField): PositioningColumn | undefined {
  return data.columns.find((column) => column.field === field);
}

/**
 * The open interest to draw: its value in a currency when the venue gives it (comparable
 * across venues and contracts), else the contracts in the base asset (an inverse swap).
 */
export function openInterestShown(data: Positioning): { column: PositioningColumn; currency: string | null } | null {
  const valued = columnOf(data, "open_interest_value");
  if (valued && data.value_currency) return { column: valued, currency: data.value_currency };
  const contracts = columnOf(data, "open_interest");
  return contracts ? { column: contracts, currency: null } : null;
}

/** Relative change from the first to the last value of an amount (``null`` if undefined). */
export function relativeChange(column: PositioningColumn): number | null {
  const { first, latest } = column;
  if (first === null || latest === null || first <= 0) return null;
  return latest / first - 1;
}

/** Points of a column for a chart: one per instant, ``null`` where the venue skipped one. */
export function columnPoints(data: Positioning, column: PositioningColumn): { time: string; value: number | null }[] {
  return data.times.map((time, index) => ({ time: String(time), value: column.values[index] ?? null }));
}

/** Names of the venues the platform knows; another venue is shown as it is called. */
const VENUE_NAMES: Readonly<Record<string, string>> = { okx: "OKX", binance: "Binance", bybit: "Bybit", deribit: "Deribit" };

/** How a venue is written (``okx`` → ``OKX``; an unknown ``kraken`` → ``Kraken``). */
export function venueLabel(venue: string): string {
  return VENUE_NAMES[venue] ?? venue.charAt(0).toUpperCase() + venue.slice(1);
}

/** The venue to ask: the one chosen while it is offered, else the first offered. */
export function chosenVenue(offered: readonly string[] | undefined, chosen: string | null): string | null {
  if (!offered || offered.length === 0) return null;
  return chosen !== null && offered.includes(chosen) ? chosen : (offered[0] ?? null);
}
