/**
 * Data hooks: one per API capability, cached by TanStack Query.
 *
 * Analyses are deterministic for a given request (seeded Monte Carlo included), so they are
 * cached by their request body. While a new request runs, the previous result stays on
 * screen (`placeholderData: keepPreviousData`): refetches keep the frame.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError, unwrap, type Schemas } from "@/lib/api/client";
import type { Locale } from "@/lib/i18n/messages";

const MINUTE = 60_000;

export type Interval = Schemas["Frequency"];

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => unwrap(await api.GET("/health/ready")),
    // While the API is down, look again every few seconds: the screens recover by themselves.
    refetchInterval: (query) => (query.state.status === "error" ? 5_000 : MINUTE),
    retry: 1,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/providers")),
    staleTime: 10 * MINUTE,
  });
}

export function useModules(language: Locale) {
  return useQuery({
    queryKey: ["modules", language],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/modules", { params: { query: { language } } })),
    staleTime: 10 * MINUTE,
  });
}

export function useBars(symbol: string, interval: Interval, start: string | null) {
  return useQuery({
    queryKey: ["bars", symbol, interval, start],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/market/bars", {
          params: { query: { symbol, interval, start: start ?? undefined } },
        }),
      ),
    enabled: symbol.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * MINUTE,
  });
}

export function useFlow(symbol: string, interval: Interval, start: string | null) {
  return useQuery({
    queryKey: ["flow", symbol, interval, start],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/market/flow", {
          params: { query: { symbol, interval, start: start ?? undefined } },
        }),
      ),
    enabled: symbol.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * MINUTE,
    retry: (count, error) => !isNotFound(error) && count < 2,
  });
}

/** Funding of the perpetual swap ``swap`` (``BTC/USDT:USDT``); disabled with ``null``. */
export function useFunding(swap: string | null, start: string | null) {
  return useQuery({
    queryKey: ["funding", swap, start],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/market/holding-rates", {
          params: { query: { symbol: swap ?? "", kind: "funding", start: start ?? undefined } },
        }),
      ),
    enabled: swap !== null,
    placeholderData: keepPreviousData,
    staleTime: 5 * MINUTE,
    retry: (count, error) => !isNotFound(error) && count < 2,
  });
}

/** An economic series (``FNG``, the €STR...) from ``start``; disabled with an empty id. */
export function useEconomic(seriesId: string, start: string | null) {
  return useQuery({
    queryKey: ["economic", seriesId, start],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/economic/series", {
          params: { query: { series_id: seriesId, start: start ?? undefined } },
        }),
      ),
    enabled: seriesId.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30 * MINUTE,
    retry: (count, error) => !isNotFound(error) && count < 2,
  });
}

/** Whether the API answered that the data does not exist (nothing to retry). */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function useComparison(request: Schemas["CompareRequest"] | null) {
  return useQuery({
    queryKey: ["compare", request],
    queryFn: async () =>
      unwrap(await api.POST("/api/v1/market/compare", { body: request as Schemas["CompareRequest"] })),
    enabled: request !== null && request.symbols.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * MINUTE,
  });
}

export function useQuality(symbol: string, start: string | null) {
  return useQuery({
    queryKey: ["quality", symbol, start],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/market/quality", {
          params: { query: { symbol, start: start ?? undefined } },
        }),
      ),
    enabled: symbol.length > 0,
    staleTime: 10 * MINUTE,
  });
}

export function useRiskFree(currency: string, start: string) {
  return useQuery({
    queryKey: ["risk-free", currency, start],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/rates/risk-free", { params: { query: { currency, start } } })),
    staleTime: 30 * MINUTE,
  });
}

export function useAnalytics(portfolio: Schemas["PortfolioIn"] | null) {
  return useQuery({
    queryKey: ["analytics", portfolio],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/portfolios/analytics", {
          body: portfolio as Schemas["PortfolioIn"],
        }),
      ),
    enabled: portfolio !== null,
    placeholderData: keepPreviousData,
    staleTime: 5 * MINUTE,
  });
}

export function useSimulation(request: Schemas["SimulationIn"] | null) {
  return useQuery({
    queryKey: ["simulation", request],
    queryFn: async () =>
      unwrap(await api.POST("/api/v1/simulations", { body: request as Schemas["SimulationIn"] })),
    enabled: request !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function useOptimization(request: Schemas["OptimizationIn"] | null) {
  return useQuery({
    queryKey: ["optimization", request],
    queryFn: async () =>
      unwrap(await api.POST("/api/v1/optimizations", { body: request as Schemas["OptimizationIn"] })),
    enabled: request !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function usePlan(request: Schemas["PlanIn"] | null) {
  return useQuery({
    queryKey: ["plan", request],
    queryFn: async () => unwrap(await api.POST("/api/v1/plans", { body: request as Schemas["PlanIn"] })),
    enabled: request !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

// ── Saved portfolios ─────────────────────────────────────────────────

const SAVED = ["saved-portfolios"] as const;

/** Which problem of the API an error is (the fragment of its `type`), if it is one. */
export function problemKind(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.problem === null) return null;
  return error.problem.type.split("#").pop() ?? null;
}

export function useSavedPortfolios() {
  return useQuery({
    queryKey: SAVED,
    queryFn: async () => unwrap(await api.GET("/api/v1/portfolios", { params: { query: { limit: 200 } } })),
    // Without a database there is nothing to retry: the screen explains it instead.
    retry: (failures, error) => problemKind(error) !== "persistence-not-configured" && failures < 1,
    staleTime: MINUTE,
  });
}

/** Save a portfolio: a new record, or a new version of the one read at `saved.version`. */
export function useSavePortfolio() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ portfolio, saved }: { portfolio: Schemas["PortfolioIn"]; saved: { id: string; version: number } | null }) =>
      saved === null
        ? unwrap(await api.POST("/api/v1/portfolios", { body: portfolio }))
        : unwrap(
            await api.PUT("/api/v1/portfolios/{portfolio_id}", {
              params: { path: { portfolio_id: saved.id }, header: { "if-match": `"${saved.version}"` } },
              body: portfolio,
            }),
          ),
    onSettled: () => client.invalidateQueries({ queryKey: SAVED }),
  });
}

export function useDeleteSavedPortfolio() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, version }: { id: string; version: number }) => {
      const result = await api.DELETE("/api/v1/portfolios/{portfolio_id}", {
        params: { path: { portfolio_id: id }, header: { "if-match": `"${version}"` } },
      });
      if (!result.response.ok) unwrap(result);
    },
    onSettled: () => client.invalidateQueries({ queryKey: SAVED }),
  });
}
