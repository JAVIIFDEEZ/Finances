import { describe, expect, it } from "vitest";

import {
  CHARTED_RATIOS,
  chosenVenue,
  columnOf,
  columnPoints,
  fieldSlot,
  openInterestShown,
  positioningWindow,
  RATIO_FIELDS,
  relativeChange,
  venueLabel,
  type Positioning,
  type PositioningColumn,
} from "@/lib/util/positioning";

function column(field: PositioningColumn["field"], values: (number | null)[]): PositioningColumn {
  const present = values.filter((value): value is number => value !== null);
  return {
    field,
    kind: field.startsWith("open_interest") ? "amount" : "ratio",
    first: present[0] ?? null,
    latest: present[present.length - 1] ?? null,
    minimum: present.length ? Math.min(...present) : null,
    maximum: present.length ? Math.max(...present) : null,
    values,
  };
}

/** SYNTHETIC snapshots: three hours of a swap, a ratio skipped in the second one. */
const data: Positioning = {
  instrument: { symbol: "SYN/USDT:USDT", name: "Synthetic swap", asset_class: "crypto", currency: "USDT", exchange: null },
  venue: "okx",
  frequency: "1h",
  source: { provider: "synthetic", dataset: null, retrieved_at: "2026-11-17T00:00:00Z" },
  value_currency: "USD",
  times: ["2026-11-16T00:00:00Z", "2026-11-16T01:00:00Z", "2026-11-16T02:00:00Z"],
  columns: [column("open_interest", [100, 104, 110]), column("open_interest_value", [5_000, 5_200, 5_500]), column("long_short_accounts", [1.2, null, 1.4])],
};

describe("positioningWindow", () => {
  it("counts UTC days back and reads longer windows at a coarser spacing", () => {
    const late = new Date("2026-11-17T23:30:00-05:00"); // already the 18th in UTC
    expect(positioningWindow("7d", late)).toEqual({ start: "2026-11-11", interval: "1h" });
    expect(positioningWindow("30d", late)).toEqual({ start: "2026-10-19", interval: "4h" });
    expect(positioningWindow("90d", late)).toEqual({ start: "2026-08-20", interval: "1d" });
  });
});

describe("openInterestShown", () => {
  it("draws the value in its currency when the venue gives it", () => {
    const shown = openInterestShown(data);
    expect(shown?.column.field).toBe("open_interest_value");
    expect(shown?.currency).toBe("USD");
  });

  it("draws the contracts of an inverse swap, which has no value", () => {
    const inverse: Positioning = { ...data, value_currency: null, columns: [column("open_interest", [10, 11])] };
    expect(openInterestShown(inverse)).toEqual({ column: inverse.columns[0], currency: null });
    expect(openInterestShown({ ...data, columns: [column("long_short_accounts", [1])] })).toBeNull();
  });
});

describe("relativeChange", () => {
  it("is the move from the first to the last value", () => {
    expect(relativeChange(column("open_interest", [100, 104, 110]))).toBeCloseTo(0.1);
  });

  it("is undefined without two values or from zero", () => {
    expect(relativeChange(column("open_interest", [null]))).toBeNull();
    expect(relativeChange(column("open_interest", [0, 5]))).toBeNull();
  });
});

describe("columnPoints", () => {
  it("keeps a skipped snapshot as a gap, never a filled value", () => {
    const ratio = columnOf(data, "long_short_accounts");
    expect(ratio).toBeDefined();
    expect(columnPoints(data, ratio as PositioningColumn).map((point) => point.value)).toEqual([1.2, null, 1.4]);
    expect(columnOf(data, "taker_buy_sell")).toBeUndefined();
  });
});

describe("fieldSlot", () => {
  it("gives each field its own colour, the same whichever fields a venue publishes", () => {
    expect(fieldSlot("open_interest")).toBe(fieldSlot("open_interest_value"));
    const slots = RATIO_FIELDS.map(fieldSlot);
    expect(new Set([0, ...slots]).size).toBe(RATIO_FIELDS.length + 1);
  });

  it("draws the ratios of how traders stand and only lists the takers' flow", () => {
    expect(CHARTED_RATIOS.every((field) => RATIO_FIELDS.includes(field))).toBe(true);
    expect(CHARTED_RATIOS).not.toContain("taker_buy_sell");
  });
});

describe("venues", () => {
  it("writes the known venues by their name and any other one capitalised", () => {
    expect(venueLabel("okx")).toBe("OKX");
    expect(venueLabel("kraken")).toBe("Kraken");
  });

  it("keeps the venue chosen while it is offered and falls back to the first", () => {
    expect(chosenVenue(["okx", "binance"], "binance")).toBe("binance");
    expect(chosenVenue(["okx", "binance"], "bybit")).toBe("okx");
    expect(chosenVenue(["okx"], null)).toBe("okx");
    expect(chosenVenue([], "okx")).toBeNull();
    expect(chosenVenue(undefined, "okx")).toBeNull();
  });
});
