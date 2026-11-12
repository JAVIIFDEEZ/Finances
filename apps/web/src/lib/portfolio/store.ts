/**
 * The portfolio being worked on, shared by every analysis screen and kept in this browser.
 *
 * It is a draft: the API recomputes everything from it. Saving it in the server is explicit
 * (see ``SavedPortfolios``); ``saved`` then remembers which record the draft comes from and
 * the version read, so a later save cannot overwrite a change made elsewhere.
 */

import { z } from "zod";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { Schemas } from "@/lib/api/client";

export const WEIGHT_TOLERANCE = 1e-6;

export type RebalanceChoice = "periodic" | "quarterly" | "threshold" | "buy_and_hold";

export interface HoldingDraft {
  symbol: string;
  /** Percent (0–100), as the user types it. */
  weight: number;
}

export interface PortfolioDraft {
  name: string;
  holdings: HoldingDraft[];
  baseCurrency: string | null;
  rebalance: RebalanceChoice;
  start: string;
  allowShort: boolean;
}

export const DEFAULT_PORTFOLIO: PortfolioDraft = {
  name: "Núcleo Ibex",
  holdings: [
    { symbol: "SAN.MC", weight: 30 },
    { symbol: "ITX.MC", weight: 25 },
    { symbol: "IBE.MC", weight: 25 },
    { symbol: "BBVA.MC", weight: 20 },
  ],
  baseCurrency: "EUR",
  rebalance: "periodic",
  start: "2019-01-01",
  allowShort: false,
};

const SYMBOL = /^[A-Za-z0-9.^=\-_/:]{1,32}$/;

/** Live validation of a draft: the same rules as the API's ``weight_problems``. */
export const portfolioSchema = z
  .object({
    name: z.string().trim().min(1).max(80),
    holdings: z
      .array(z.object({ symbol: z.string().regex(SYMBOL), weight: z.number().finite() }))
      .min(1),
    allowShort: z.boolean(),
  })
  .superRefine((draft, context) => {
    const symbols = draft.holdings.map((h) => h.symbol.toUpperCase());
    const duplicated = symbols.filter((s, i) => symbols.indexOf(s) !== i);
    if (duplicated.length > 0) {
      context.addIssue({ code: "custom", message: `duplicated: ${[...new Set(duplicated)].join(", ")}` });
    }
    const total = draft.holdings.reduce((sum, h) => sum + h.weight, 0);
    if (Math.abs(total - 100) > WEIGHT_TOLERANCE * 100) {
      context.addIssue({ code: "custom", message: `sum ${total.toFixed(2)} %` });
    }
    if (!draft.allowShort && draft.holdings.some((h) => h.weight < 0)) {
      context.addIssue({ code: "custom", message: "negative weights" });
    }
  });

function rebalanceBody(choice: RebalanceChoice): Schemas["RebalanceIn"] {
  switch (choice) {
    case "buy_and_hold":
      return { kind: "buy_and_hold" };
    case "threshold":
      return { kind: "threshold", band: 0.05 };
    case "quarterly":
      return { kind: "periodic", frequency: "1q" };
    default:
      return { kind: "periodic", frequency: "1mo" };
  }
}

/** The API request body of a draft (weights as decimals). */
export function toPortfolioIn(draft: PortfolioDraft): Schemas["PortfolioIn"] {
  return {
    name: draft.name.trim() || "Portfolio",
    holdings: draft.holdings.map((h) => ({ symbol: h.symbol.trim().toUpperCase(), weight: h.weight / 100 })),
    base_currency: draft.baseCurrency,
    rebalance: rebalanceBody(draft.rebalance),
    start: draft.start || null,
    allow_short: draft.allowShort,
  };
}

function rebalanceChoice(rebalance: Schemas["RebalanceIn"] | undefined): RebalanceChoice {
  if (rebalance?.kind === "buy_and_hold") return "buy_and_hold";
  if (rebalance?.kind === "threshold") return "threshold";
  return rebalance?.frequency === "1q" ? "quarterly" : "periodic";
}

/** The draft of a saved definition (weights back to percent, without float noise). */
export function fromPortfolioIn(portfolio: Schemas["PortfolioIn"]): PortfolioDraft {
  return {
    name: portfolio.name ?? "Portfolio",
    holdings: portfolio.holdings.map((h) => ({
      symbol: h.symbol,
      weight: Math.round(h.weight * 1e8) / 1e6,
    })),
    baseCurrency: portfolio.base_currency ?? null,
    rebalance: rebalanceChoice(portfolio.rebalance),
    start: portfolio.start ?? "",
    allowShort: portfolio.allow_short ?? false,
  };
}

/** The saved record a draft comes from, and the version last read. */
export interface SavedRef {
  id: string;
  version: number;
}

interface PortfolioState {
  draft: PortfolioDraft;
  saved: SavedRef | null;
  setDraft: (draft: PortfolioDraft) => void;
  setWeights: (weights: Record<string, number>) => void;
  /** Work on a saved portfolio (or note that the draft has just been saved). */
  open: (record: Schemas["SavedPortfolioOut"]) => void;
  /** Keep the draft but forget the record it came from (it was deleted). */
  detach: () => void;
  reset: () => void;
}

export const usePortfolio = create<PortfolioState>()(
  persist(
    (set) => ({
      draft: DEFAULT_PORTFOLIO,
      saved: null,
      setDraft: (draft) => set({ draft }),
      open: (record) =>
        set({
          draft: fromPortfolioIn(record.portfolio),
          saved: { id: record.id, version: record.version },
        }),
      detach: () => set({ saved: null }),
      setWeights: (weights) =>
        set((state) => ({
          draft: {
            ...state.draft,
            holdings: state.draft.holdings.map((h) => ({
              ...h,
              weight: (weights[h.symbol] ?? 0) * 100,
            })),
          },
        })),
      reset: () => set({ draft: DEFAULT_PORTFOLIO, saved: null }),
    }),
    {
      name: "investinglab.portfolio",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      // Rehydrated after mount (see Providers): the first render matches the server's.
      skipHydration: true,
    },
  ),
);
