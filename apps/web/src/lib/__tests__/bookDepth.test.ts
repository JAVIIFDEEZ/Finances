import { describe, expect, it } from "vitest";

import { bandOf, bandPoints, chosenBand, defaultBand, lastOf, liquidityOf, type BookBand, type BookDepth } from "@/lib/util/bookDepth";

function band(value: number, bid: (number | null)[], ask: (number | null)[], valued = true): BookBand {
  const imbalance = bid.map((b, i) => {
    const a = ask[i] ?? null;
    return b === null || a === null || b + a === 0 ? null : (b - a) / (b + a);
  });
  const notional = (side: (number | null)[]) => side.map((q) => (q === null ? null : q * 50_000));
  const liquidity = bid.map((b, i) => {
    const a = ask[i] ?? null;
    return b === null || a === null ? null : (b + a) * 50_000;
  });
  return {
    band: value,
    bid,
    ask,
    bid_notional: valued ? notional(bid) : null,
    ask_notional: valued ? notional(ask) : null,
    imbalance,
    liquidity: valued ? liquidity : null,
    latest_bid: lastOf(bid),
    latest_ask: lastOf(ask),
    latest_imbalance: lastOf(imbalance),
    latest_liquidity: valued ? lastOf(liquidity) : null,
  };
}

/** SYNTHETIC book: three hours of a swap, the asks within ±2 % skipped in the second one. */
const data: BookDepth = {
  instrument: { symbol: "SYN/USDT:USDT", name: "Synthetic swap", asset_class: "crypto", currency: "USDT", exchange: null },
  venue: "binance",
  frequency: "1h",
  source: { provider: "synthetic", dataset: null, retrieved_at: "2026-11-21T00:00:00Z" },
  notional_currency: "USDT",
  times: ["2026-11-20T00:00:00Z", "2026-11-20T01:00:00Z", "2026-11-20T02:00:00Z"],
  bands: [band(1, [10, 11, 12], [8, 9, 10]), band(2, [30, 31, 32], [25, null, 27])],
};

describe("bands", () => {
  it("starts on ±2 %, or the nearest band a venue publishes", () => {
    expect(defaultBand([0.2, 1, 2, 5])).toBe(2);
    expect(defaultBand([1, 3, 5])).toBe(1); // as near as 3, and narrower comes first
    expect(defaultBand([0.2, 5])).toBe(0.2);
    expect(defaultBand([])).toBeNull();
  });

  it("keeps the band chosen while it is published", () => {
    expect(chosenBand([1, 2, 5], 5)).toBe(5);
    expect(chosenBand([1, 2], 0.2)).toBe(2); // an inverse swap has no ±0.2 %
    expect(chosenBand([1, 2], null)).toBe(2);
    expect(bandOf(data, 3)).toBeUndefined();
  });
});

describe("liquidityOf", () => {
  it("is the value on both sides when the venue gives it", () => {
    const wide = bandOf(data, 2) as BookBand;
    const shown = liquidityOf(data, wide);
    expect(shown.valued).toBe(true);
    expect(shown.unit).toBe("USDT");
    expect(shown.values).toEqual([55 * 50_000, null, 59 * 50_000]);
  });

  it("is the quantity of an inverse swap, an instant missing a side left empty", () => {
    const inverse: BookDepth = { ...data, notional_currency: null, bands: [band(2, [30, 31], [25, null], false)] };
    const shown = liquidityOf(inverse, inverse.bands[0] as BookBand);
    expect(shown).toEqual({ values: [55, null], unit: null, valued: false });
  });
});

describe("points", () => {
  it("keeps a skipped snapshot as a gap", () => {
    const wide = bandOf(data, 2) as BookBand;
    expect(bandPoints(data, wide.imbalance).map((point) => point.value)).toEqual([wide.imbalance[0], null, wide.imbalance[2]]);
    expect(lastOf([1, null, 3, null])).toBe(3);
    expect(lastOf([null, null])).toBeNull();
  });
});
