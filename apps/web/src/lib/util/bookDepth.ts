/**
 * Presentation helpers of order-book depth (ADR-0044): which band to show first, how the
 * liquidity of a band is drawn when the venue gives no value, and the points of a chart.
 * The API sends what the venue publishes; nothing here fills in what it does not.
 */

import type { Schemas } from "@/lib/api/client";

export type BookDepth = Schemas["BookDepthOut"];
export type BookBand = Schemas["BookBandOut"];

/** The band read first: ±2 % (the liquidity desks quote), else the nearest one published. */
export const PREFERRED_BAND = 2;

export function defaultBand(bands: readonly number[]): number | null {
  if (bands.length === 0) return null;
  return bands.reduce((best, band) => (Math.abs(band - PREFERRED_BAND) < Math.abs(best - PREFERRED_BAND) ? band : best));
}

/** The band chosen while it is published, else the default one. */
export function chosenBand(bands: readonly number[], chosen: number | null): number | null {
  return chosen !== null && bands.includes(chosen) ? chosen : defaultBand(bands);
}

/** The data of one band, if the venue publishes it. */
export function bandOf(data: BookDepth, band: number): BookBand | undefined {
  return data.bands.find((item) => item.band === band);
}

/** One point per instant of the book, ``null`` where the venue skipped a snapshot. */
export function bandPoints(data: BookDepth, values: readonly (number | null)[]): { time: string; value: number | null }[] {
  return data.times.map((time, index) => ({ time: String(time), value: values[index] ?? null }));
}

/**
 * What rests on both sides of a band: its value when the venue gives it (comparable across
 * contracts and venues), else the quantity in the base asset (an inverse swap). A side
 * missing at an instant leaves that instant empty rather than half counted.
 */
export function liquidityOf(data: BookDepth, band: BookBand): { values: (number | null)[]; unit: string | null; valued: boolean } {
  if (band.liquidity && data.notional_currency) {
    return { values: band.liquidity, unit: data.notional_currency, valued: true };
  }
  const values = band.bid.map((bid, index) => {
    const ask = band.ask[index] ?? null;
    return bid === null || ask === null ? null : bid + ask;
  });
  return { values, unit: null, valued: false };
}

/** The last value of a series that is not missing. */
export function lastOf(values: readonly (number | null)[]): number | null {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index];
    if (value !== null && value !== undefined) return value;
  }
  return null;
}
