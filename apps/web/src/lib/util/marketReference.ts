/**
 * Presentation helpers of a market's snapshot and ranking (ADR-0045): the dominance as rows
 * that add up to the whole, and the share of each ranked asset. The API sends what the source
 * publishes; a share it does not give is never made up.
 */

import type { Schemas } from "@/lib/api/client";

export type MarketSnapshot = Schemas["MarketSnapshotOut"];
export type MarketCaps = Schemas["MarketCapsOut"];

/** Rows of the dominance chart: the assets the source publishes, then everything else. */
export function dominanceRows(snapshot: MarketSnapshot, othersLabel: string): { label: string; share: number }[] {
  const rows = snapshot.dominance.map((item) => ({ label: item.symbol, share: item.share }));
  return snapshot.others > 0 ? [...rows, { label: othersLabel, share: snapshot.others }] : rows;
}

/** The share of an asset in the whole market, from its capitalisation and the total. */
export function shareOfTotal(marketCap: number | null, total: number | null | undefined): number | null {
  if (marketCap === null || total === null || total === undefined || !(total > 0)) return null;
  return marketCap / total;
}

/** Names of the reference sources the platform knows; another one is shown capitalised. */
const SOURCE_NAMES: Readonly<Record<string, string>> = { coingecko: "CoinGecko" };

/** How a source is written (``coingecko`` → ``CoinGecko``; an unknown ``kaiko`` → ``Kaiko``). */
export function sourceLabel(provider: string): string {
  return SOURCE_NAMES[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** How old a snapshot is, in whole minutes (never negative: clocks drift). */
export function ageInMinutes(asOf: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(asOf).getTime()) / 60_000));
}
