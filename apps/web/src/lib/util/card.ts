/**
 * Presentation helpers of the card of an instrument (ADR-0040): how each fact of a pillar is
 * worded and where a score sits on its meter. The API sends data; the words are chosen here.
 */

import type { Schemas } from "@/lib/api/client";
import type { Formatter } from "@/lib/i18n/format";

export type Pillar = Schemas["PillarOut"];
export type Fact = Schemas["FactOut"];

/** Ratios that are a move from somewhere, shown with their sign (``+4,8 %``). */
const SIGNED: ReadonlySet<string> = new Set(["price_vs_average", "support_distance", "resistance_distance", "total_return", "funding_last", "funding_mean"]);

/** Facts a pillar shows as its headline, not in its list. */
const HEADLINE: Readonly<Record<string, readonly string[]>> = { technical: ["verdict", "alignment"] };

/** Where the words of each coded fact live in the messages. */
const CODE_PREFIX: Readonly<Record<string, string>> = { verdict: "confluence.verdict", trend: "trend", state: "card.state", worst: "markets.severity" };

/** The facts a pillar lists under its headline, in the API's order. */
export function listedFacts(pillar: Pillar): Fact[] {
  const headline = HEADLINE[pillar.pillar] ?? [];
  return pillar.facts.filter((fact) => !headline.includes(fact.key));
}

/** The fact named ``key`` of a pillar, if it has it. */
export function factOf(pillar: Pillar, key: string): Fact | undefined {
  return pillar.facts.find((fact) => fact.key === key);
}

/** The message key that words a coded value (the caller falls back to the value itself). */
export function codeKey(key: string, value: string): string {
  return `${CODE_PREFIX[key] ?? `card.code.${key}`}.${value}`;
}

/**
 * A fact's value as text. ``words`` translates a message key, or returns ``null`` if the web
 * does not know it (a code the API added later is shown as it comes). Never ``NaN``: «—».
 */
export function factText(fact: Fact, fmt: Formatter, words: (key: string) => string | null): string {
  const value = fact.value;
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") {
    if (fact.unit === "date") return fmt.date(value);
    return words(codeKey(fact.key, value)) ?? value;
  }
  switch (fact.unit) {
    case "ratio":
      return SIGNED.has(fact.key) ? fmt.signedPercent(value, 1) : fmt.percent(value, 1);
    case "count":
      return fmt.number(value, 0);
    default:
      return fmt.number(value, 2);
  }
}

/** Which way a score in [-1, 1] points; within ``dead`` of zero, nowhere. */
export function scoreDirection(score: number | null | undefined, dead = 0.005): "up" | "down" | "flat" {
  if (score == null || Math.abs(score) < dead) return "flat";
  return score > 0 ? "up" : "down";
}

/**
 * The filled part of a meter from -1 to +1, in percent of its track: it grows from the
 * middle towards the side the score points to. A score beyond the scale is drawn at its end.
 */
export function meterFill(score: number | null | undefined): { left: number; width: number } {
  if (score == null || !Number.isFinite(score)) return { left: 50, width: 0 };
  const clamped = Math.max(-1, Math.min(1, score));
  const width = Math.abs(clamped) * 50;
  return { left: clamped < 0 ? 50 - width : 50, width };
}
