import { describe, expect, it } from "vitest";

import { DEFAULT_PORTFOLIO, portfolioSchema, toPortfolioIn, type PortfolioDraft } from "@/lib/portfolio/store";

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
