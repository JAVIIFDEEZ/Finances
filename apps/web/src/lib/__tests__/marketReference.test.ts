import { describe, expect, it } from "vitest";

import { ageInMinutes, dominanceRows, shareOfTotal, sourceLabel, type MarketSnapshot } from "@/lib/util/marketReference";

/** SYNTHETIC snapshot of a market. */
const snapshot: MarketSnapshot = {
  asset_class: "crypto",
  currency: "USD",
  as_of: "2026-11-22T15:00:00Z",
  source: { provider: "synthetic", dataset: null, retrieved_at: "2026-11-22T15:01:00Z" },
  total_market_cap: 1_000,
  total_volume_24h: null,
  market_cap_change_24h: null,
  assets: null,
  dominance: [
    { symbol: "SYNA", share: 0.5 },
    { symbol: "SYNB", share: 0.2 },
  ],
  others: 0.3,
};

describe("dominanceRows", () => {
  it("lists the published shares and then the rest, adding up to the whole", () => {
    const rows = dominanceRows(snapshot, "Others");
    expect(rows.map((row) => row.label)).toEqual(["SYNA", "SYNB", "Others"]);
    expect(rows.reduce((sum, row) => sum + row.share, 0)).toBeCloseTo(1);
  });

  it("adds no empty row when the published shares are the whole", () => {
    expect(dominanceRows({ ...snapshot, others: 0 }, "Others")).toHaveLength(2);
  });
});

describe("shareOfTotal", () => {
  it("is the capitalisation over the total, or nothing without one of them", () => {
    expect(shareOfTotal(250, 1_000)).toBeCloseTo(0.25);
    expect(shareOfTotal(null, 1_000)).toBeNull();
    expect(shareOfTotal(250, 0)).toBeNull();
    expect(shareOfTotal(250, undefined)).toBeNull();
  });
});

describe("ageInMinutes", () => {
  it("counts whole minutes and never goes negative", () => {
    expect(ageInMinutes("2026-11-22T15:00:00Z", new Date("2026-11-22T15:07:30Z"))).toBe(7);
    expect(ageInMinutes("2026-11-22T15:00:00Z", new Date("2026-11-22T14:59:00Z"))).toBe(0);
  });
});

describe("sourceLabel", () => {
  it("writes a known source by its name and capitalises any other", () => {
    expect(sourceLabel("coingecko")).toBe("CoinGecko");
    expect(sourceLabel("synthetic")).toBe("Synthetic");
  });
});
