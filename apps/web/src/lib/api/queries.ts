/**
 * Data hooks: one per API capability, cached by TanStack Query.
 *
 * Analyses are deterministic for a given request (seeded Monte Carlo included), so they are
 * cached by their request body. While a new request runs, the previous result stays on
 * screen (`placeholderData: keepPreviousData`): refetches keep the frame.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api/client";
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
