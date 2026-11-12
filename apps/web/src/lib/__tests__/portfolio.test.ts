import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { problemKind } from "@/lib/api/queries";
import {
  DEFAULT_PORTFOLIO,
  fromPortfolioIn,
  portfolioSchema,
  toPortfolioIn,
  usePortfolio,
  type PortfolioDraft,
} from "@/lib/portfolio/store";

function draft(changes: Partial<PortfolioDraft>): PortfolioDraft {
  return { ...DEFAULT_PORTFOLIO, ...changes };
}

describe("portfolio drafts", () => {
  it("accepts the default portfolio", () => {
    expect(portfolioSchema.safeParse(DEFAULT_PORTFOLIO).success).toBe(true);
  });

  it.each([
    ["weights that do not add up", draft({ holdings: [{ symbol: "SAN.MC", weight: 60 }] }), "sum 60.00 %"],
    [
      "duplicated symbols",
      draft({ holdings: [{ symbol: "SAN.MC", weight: 50 }, { symbol: "san.mc", weight: 50 }] }),
      "duplicated: SAN.MC",
    ],
    [
      "short positions when not allowed",
      draft({ holdings: [{ symbol: "SAN.MC", weight: 120 }, { symbol: "ITX.MC", weight: -20 }] }),
      "negative weights",
    ],
  ])("rejects %s", (_name, value, message) => {
    const result = portfolioSchema.safeParse(value);
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.message)).toContain(message);
  });

  it("allows shorts when asked", () => {
    const shorts = draft({ allowShort: true, holdings: [{ symbol: "SAN.MC", weight: 120 }, { symbol: "ITX.MC", weight: -20 }] });
    expect(portfolioSchema.safeParse(shorts).success).toBe(true);
  });

  it("maps a draft to the API request with decimal weights", () => {
    const body = toPortfolioIn(draft({ rebalance: "threshold", holdings: [{ symbol: " san.mc ", weight: 100 }] }));
    expect(body.holdings).toEqual([{ symbol: "SAN.MC", weight: 1 }]);
    expect(body.rebalance).toEqual({ kind: "threshold", band: 0.05 });
    expect(body.base_currency).toBe("EUR");
    expect(toPortfolioIn(draft({ rebalance: "quarterly" })).rebalance).toEqual({ kind: "periodic", frequency: "1q" });
  });
});

describe("saved portfolios", () => {
  const record = (changes: Partial<PortfolioDraft> = {}, version = 1) => ({
    id: "5e0c2d8e-7a52-4d6b-9d0c-3f1f6c5a9b11",
    version,
    created_at: "2026-11-12T09:00:00Z",
    updated_at: "2026-11-12T09:00:00Z",
    portfolio: toPortfolioIn(draft(changes)),
  });

  it.each([
    ["the default", {}],
    ["thirds, without float noise", { holdings: [{ symbol: "A", weight: 33.33 }, { symbol: "B", weight: 33.33 }, { symbol: "C", weight: 33.34 }] }],
    ["shorts and no base currency", { holdings: [{ symbol: "A", weight: 130 }, { symbol: "B", weight: -30 }], allowShort: true, baseCurrency: null }],
    ["quarterly rebalancing", { rebalance: "quarterly" as const }],
    ["threshold rebalancing", { rebalance: "threshold" as const }],
    ["buy and hold, no start", { rebalance: "buy_and_hold" as const, start: "" }],
  ])("reads back the draft that was saved: %s", (_, changes) => {
    const original = draft(changes);

    expect(fromPortfolioIn(toPortfolioIn(original))).toEqual(original);
  });

  it("fills what an API definition may omit", () => {
    expect(fromPortfolioIn({ holdings: [{ symbol: "A", weight: 1 }] })).toEqual({
      name: "Portfolio",
      holdings: [{ symbol: "A", weight: 100 }],
      baseCurrency: null,
      rebalance: "periodic",
      start: "",
      allowShort: false,
    });
  });

  it("remembers which record the draft comes from, and its version", () => {
    const store = usePortfolio.getState();

    store.open(record({ name: "Saved" }, 3));
    expect(usePortfolio.getState().saved).toEqual({ id: record().id, version: 3 });
    expect(usePortfolio.getState().draft.name).toBe("Saved");

    usePortfolio.getState().setWeights({ "SAN.MC": 1 });
    expect(usePortfolio.getState().saved?.version).toBe(3); // editing keeps the link

    usePortfolio.getState().detach();
    expect(usePortfolio.getState().saved).toBeNull();
    expect(usePortfolio.getState().draft.name).toBe("Saved"); // the work is not lost

    usePortfolio.getState().open(record());
    usePortfolio.getState().reset();
    expect(usePortfolio.getState()).toMatchObject({ draft: DEFAULT_PORTFOLIO, saved: null });
  });

  it("names the problem the API reported", () => {
    const problem = (kind: string) =>
      new ApiError(409, { type: `https://example.test/api.md#${kind}`, title: "t", status: 409, detail: "d", instance: "urn:request:1" });

    expect(problemKind(problem("name-conflict"))).toBe("name-conflict");
    expect(problemKind(problem("persistence-not-configured"))).toBe("persistence-not-configured");
    expect(problemKind(new ApiError(500, null))).toBeNull();
    expect(problemKind(new TypeError("Failed to fetch"))).toBeNull();
  });
});
