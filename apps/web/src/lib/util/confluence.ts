/**
 * Presentation helpers of the confluence across timeframes (ADR-0038): the frame presets,
 * the figure each rule shows and the side its bias points to.
 */

import type { Schemas } from "@/lib/api/client";

export type Frame = Schemas["FrameOut"];
export type Rule = Schemas["RuleOut"];
export type FrameCode = Frame["frequency"];
export type Bias = Rule["bias"];

/** Sets of frames offered: every source serves the positional one; intraday needs a venue. */
export const PRESETS = {
  positional: ["1d", "1w", "1mo"],
  intraday: ["15m", "1h", "4h", "1d"],
} as const satisfies Record<string, readonly FrameCode[]>;
export type Preset = keyof typeof PRESETS;

/** The side a bias points to, for its mark. */
export function biasSide(bias: Bias): "up" | "down" | "flat" {
  return bias === "bullish" ? "up" : bias === "bearish" ? "down" : "flat";
}

/** The side of a signed score (a frame's net, the alignment). */
export function scoreSide(score: number | null | undefined): "up" | "down" | "flat" {
  if (score == null || score === 0) return "flat";
  return score > 0 ? "up" : "down";
}

/** The first frame that could be read, to show its rules by default. */
export function firstReadable(frames: readonly Frame[]): Frame | undefined {
  return frames.find((frame) => frame.issue === null);
}

type Numbers = (value: number | null | undefined, digits?: number) => string;

/**
 * The figures a rule compared, as text: an oscillator's value, the average a close is
 * measured against, a band's two bounds or the MACD and its signal.
 */
export function ruleFigure(rule: Rule, number: Numbers, priceDigits: number): string {
  const v = rule.values;
  switch (rule.name) {
    case "MACD":
      return `${number(v.macd, priceDigits)} / ${number(v.signal, priceDigits)}`;
    case "BOLLINGER":
      return `${number(v.lower, priceDigits)} – ${number(v.upper, priceDigits)}`;
    case "ADX":
      return `${number(v.adx, 1)} · +DI ${number(v.plus_di, 1)} / −DI ${number(v.minus_di, 1)}`;
    case "SMA_20":
    case "SMA_50":
    case "EMA_12":
    case "EMA_26":
      return number(v.average, priceDigits);
    default:
      return number(Object.values(v)[0], 1);
  }
}

/** The rules of each style, keeping their order. */
export function byStyle(rules: readonly Rule[]): { style: Rule["style"]; rules: Rule[] }[] {
  return (["trend", "reversal"] as const)
    .map((style) => ({ style, rules: rules.filter((rule) => rule.style === style) }))
    .filter((group) => group.rules.length > 0);
}

/** A figure with its sign written out (``+0,42``); zero and missing values as they are. */
export function signed(text: string, value: number | null | undefined): string {
  return value != null && value > 0 ? `+${text}` : text;
}
