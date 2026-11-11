/**
 * Chart tokens: the validated data-viz palette, one selected step per theme.
 *
 * The interface uses the same values through CSS variables (src/app/globals.css). Every
 * categorical palette here was run through the palette validator for its surface; see
 * docs/adr/0028-institutional-web-app.md.
 */

export type ThemeName = "light" | "dark";

export interface ChartTokens {
  surface: string;
  plane: string;
  text: string;
  text2: string;
  muted: string;
  grid: string;
  axis: string;
  /** Categorical slots in their fixed order: colour follows the entity, never its rank. */
  series: readonly string[];
  /** Sequential blue, light → dark (heat of a magnitude). */
  sequential: readonly string[];
  /** Diverging blue ↔ red around a neutral grey. */
  diverging: { negative: string; neutral: string; positive: string };
  up: string;
  down: string;
  good: string;
  warning: string;
  critical: string;
}

export const TOKENS: Record<ThemeName, ChartTokens> = {
  light: {
    surface: "#fcfcfb",
    plane: "#f9f9f7",
    text: "#0b0b0b",
    text2: "#52514e",
    muted: "#898781",
    grid: "#e1e0d9",
    axis: "#c3c2b7",
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    sequential: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    diverging: { negative: "#e34948", neutral: "#f0efec", positive: "#2a78d6" },
    up: "#006300",
    down: "#d03b3b",
    good: "#0ca30c",
    warning: "#fab219",
    critical: "#d03b3b",
  },
  dark: {
    surface: "#1a1a19",
    plane: "#0d0d0d",
    text: "#f0efec",
    text2: "#c3c2b7",
    muted: "#898781",
    grid: "#2c2c2a",
    axis: "#383835",
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    sequential: ["#104281", "#184f95", "#1c5cab", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"],
    diverging: { negative: "#e66767", neutral: "#383835", positive: "#3987e5" },
    up: "#0ca30c",
    down: "#e66767",
    good: "#0ca30c",
    warning: "#fab219",
    critical: "#d03b3b",
  },
};

/** The colour of the n-th entity (0-based) in a categorical palette of at most eight. */
export function seriesColor(tokens: ChartTokens, index: number): string {
  return tokens.series[index % tokens.series.length] ?? tokens.series[0] ?? tokens.text;
}
