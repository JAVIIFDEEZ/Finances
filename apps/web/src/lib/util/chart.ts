/**
 * Geometry and reading helpers of the charts: the panes of a stacked chart, the marks of a
 * time axis without gaps, the ticks of a logarithmic price scale and what a bar says against
 * the one before. Pure functions: the components only draw what these return.
 */

// ── Panes ────────────────────────────────────────────────────────────

export interface PaneSpec<T extends string = string> {
  id: T;
  height: number;
}

export interface Pane<T extends string = string> extends PaneSpec<T> {
  /** Pixels from the top of the chart to the top of the pane's plot. */
  top: number;
}

/** Stack panes from ``top`` down with ``gap`` between them; ``foot`` is kept under the last. */
export function paneLayout<T extends string>(
  specs: readonly PaneSpec<T>[],
  { top = 8, gap = 10, foot = 0 }: { top?: number; gap?: number; foot?: number } = {},
): { panes: Pane<T>[]; height: number } {
  const panes: Pane<T>[] = [];
  let cursor = top;
  for (const spec of specs) {
    panes.push({ ...spec, top: cursor });
    cursor += spec.height + gap;
  }
  return { panes, height: (specs.length > 0 ? cursor - gap : top) + foot };
}

// ── Time axis ────────────────────────────────────────────────────────

/** The calendar units a time axis can mark, finest first. */
export const TICK_UNITS = ["day", "week", "month", "quarter", "year"] as const;
export type TickUnit = (typeof TICK_UNITS)[number];

function parts(time: string): { year: number; month: number; day: number } {
  return { year: Number(time.slice(0, 4)), month: Number(time.slice(5, 7)), day: Number(time.slice(8, 10)) };
}

/** Monday-based week number since the epoch, from the calendar date the bar carries. */
function week(time: string): number {
  const { year, month, day } = parts(time);
  const days = Math.floor(Date.UTC(year, month - 1, day) / 86_400_000);
  return Math.floor((days + 3) / 7); // 1970-01-01 was a Thursday
}

/**
 * Whether ``current`` is the first bar of its ``unit``, given the bar before it. Times are
 * read as written (the market's calendar date), never converted to another zone.
 */
export function unitStart(previous: string, current: string, unit: TickUnit): boolean {
  switch (unit) {
    case "day":
      return previous.slice(0, 10) !== current.slice(0, 10);
    case "week":
      return week(previous) !== week(current);
    case "month":
      return previous.slice(0, 7) !== current.slice(0, 7);
    case "quarter": {
      const a = parts(previous);
      const b = parts(current);
      return a.year !== b.year || Math.floor((a.month - 1) / 3) !== Math.floor((b.month - 1) / 3);
    }
    case "year":
      return previous.slice(0, 4) !== current.slice(0, 4);
  }
}

/**
 * The finest unit whose first bars, between bars ``from`` and ``to`` (inclusive), are at most
 * ``maxLabels``; years if even those are too many (the axis then drops what overlaps).
 */
export function tickUnit(times: readonly string[], from: number, to: number, maxLabels: number): TickUnit {
  const first = Math.max(1, from);
  const last = Math.min(times.length - 1, to);
  for (const unit of TICK_UNITS) {
    let count = 0;
    for (let i = first; i <= last && count <= maxLabels; i += 1) {
      if (unitStart(times[i - 1] ?? "", times[i] ?? "", unit)) count += 1;
    }
    if (count <= maxLabels) return unit;
  }
  return "year";
}

/** What the mark of a bar that starts a unit should name: the year, the month or the day. */
export function tickKind(previous: string, current: string, unit: TickUnit): "year" | "month" | "day" {
  if (unit === "year" || unitStart(previous, current, "year")) return "year";
  if (unit === "month" || unit === "quarter" || unitStart(previous, current, "month")) return "month";
  return "day";
}

// ── Value axes ───────────────────────────────────────────────────────

function niceStep(span: number, target: number): number {
  const raw = span / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const mantissa = raw / magnitude;
  const nice = mantissa <= 1 ? 1 : mantissa <= 2 ? 2 : mantissa <= 2.5 ? 2.5 : mantissa <= 5 ? 5 : 10;
  return nice * magnitude;
}

/** Round values at an even step inside ``[min, max]``, about ``target`` of them. */
export function linearTicks(min: number, max: number, target = 5): number[] {
  if (!(max > min)) return [];
  const step = niceStep(max - min, target);
  const digits = Math.max(0, -Math.floor(Math.log10(step)) + 1);
  const ticks: number[] = [];
  for (let k = Math.ceil(min / step); k * step <= max * (1 + 1e-12); k += 1) ticks.push(Number((k * step).toFixed(digits)));
  return ticks;
}

const MANTISSAS: readonly (readonly number[])[] = [[1], [1, 3], [1, 2, 5], [1, 1.5, 2, 3, 5, 7], [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9]];

/**
 * Round prices for a logarithmic scale between ``min`` and ``max`` (both > 0), about
 * ``target`` of them: 1-2-5 style values across decades, or evenly stepped ones when the
 * range is too narrow for those (a log scale over less than a doubling is almost linear).
 */
export function logTicks(min: number, max: number, target = 5): number[] {
  if (!(min > 0) || !(max > min)) return [];
  const candidates: number[][] = MANTISSAS.map((set) => {
    const ticks: number[] = [];
    for (let exponent = Math.floor(Math.log10(min)); exponent <= Math.ceil(Math.log10(max)); exponent += 1) {
      for (const mantissa of set) {
        const value = Number((mantissa * 10 ** exponent).toPrecision(12));
        if (value >= min && value <= max) ticks.push(value);
      }
    }
    return ticks;
  });
  candidates.push(linearTicks(min, max, target));
  let best: number[] = [];
  for (const ticks of candidates) {
    // Closest to the target; on a tie the earlier (rounder) set stays.
    if (best.length === 0 || Math.abs(ticks.length - target) < Math.abs(best.length - target)) best = ticks;
  }
  return best;
}

// ── Bars ─────────────────────────────────────────────────────────────

/** The change of a close against the close before it (``null`` for the first bar). */
export function barChange(closes: readonly number[], index: number): { absolute: number; relative: number } | null {
  const close = closes[index];
  const previous = closes[index - 1];
  if (close === undefined || previous === undefined || previous === 0) return null;
  return { absolute: close - previous, relative: close / previous - 1 };
}

/** The difference of two lines bar by bar (the MACD histogram: line minus signal); gaps stay gaps. */
export function spread(
  line: ReadonlyMap<string, number | null>,
  signal: ReadonlyMap<string, number | null>,
): Map<string, number | null> {
  const out = new Map<string, number | null>();
  for (const [time, value] of line) {
    const other = signal.get(time);
    out.set(time, value == null || other == null ? null : value - other);
  }
  return out;
}

/** The lowest point of a series (the trough of a drawdown); ``null`` if it has no value. */
export function trough<T extends { value: number | null }>(points: readonly T[]): (T & { value: number }) | null {
  let found: (T & { value: number }) | null = null;
  for (const point of points) {
    if (point.value != null && (found === null || point.value < found.value)) found = point as T & { value: number };
  }
  return found;
}

/** The smallest and largest defined value among ``values`` (``null`` if none). */
export function extent(values: Iterable<number | null | undefined>): readonly [number, number] | null {
  let low = Number.POSITIVE_INFINITY;
  let high = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (value == null || !Number.isFinite(value)) continue;
    if (value < low) low = value;
    if (value > high) high = value;
  }
  return low <= high ? [low, high] : null;
}

/** Of ``ticks`` on an axis ``span`` wide drawn over ``pixels``, those at least ``gap`` px apart. */
export function spacedTicks(ticks: readonly number[], span: number, pixels: number, gap = 14): number[] {
  const kept: number[] = [];
  for (const tick of [...ticks].sort((a, b) => b - a)) {
    const last = kept[kept.length - 1];
    if (last === undefined || (span > 0 && ((last - tick) / span) * pixels >= gap)) kept.push(tick);
  }
  return kept.reverse();
}

/**
 * How far to move each label, at ``positions`` along an axis (pixels, in any order), so that
 * no two are closer than ``gap``: a group that would overlap is spread around its own middle,
 * so every label stays as near its place as the others allow.
 */
export function spreadLabels(positions: readonly number[], gap: number): number[] {
  const order = positions.map((_, index) => index).sort((a, b) => (positions[a] ?? 0) - (positions[b] ?? 0));
  // Each cluster holds consecutive labels packed ``gap`` apart, starting at ``start``.
  const clusters: { start: number; members: number[]; sum: number }[] = [];
  for (const index of order) {
    const position = positions[index] ?? 0;
    clusters.push({ start: position, members: [index], sum: position });
    while (clusters.length > 1) {
      const last = clusters[clusters.length - 1];
      const before = clusters[clusters.length - 2];
      if (!last || !before || before.start + before.members.length * gap <= last.start) break;
      // Merge: the packed group sits where its labels, on average, wanted to be.
      const size = before.members.length;
      before.sum += last.sum - last.members.length * size * gap;
      before.members.push(...last.members);
      before.start = before.sum / before.members.length;
      clusters.pop();
    }
  }
  const moves = positions.map(() => 0);
  for (const cluster of clusters) {
    cluster.members.forEach((index, place) => {
      moves[index] = cluster.start + place * gap - (positions[index] ?? 0);
    });
  }
  return moves;
}
