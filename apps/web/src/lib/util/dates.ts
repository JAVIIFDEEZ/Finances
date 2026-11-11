/** Calendar helpers for request ranges (ISO dates, local calendar). */

export type RangeKey = "1m" | "6m" | "ytd" | "1y" | "5y" | "max";

function iso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** First date of a preset range ending today (``null`` for the whole history). */
export function rangeStart(range: RangeKey, today: Date = new Date()): string | null {
  const start = new Date(today);
  switch (range) {
    case "1m":
      start.setMonth(start.getMonth() - 1);
      return iso(start);
    case "6m":
      start.setMonth(start.getMonth() - 6);
      return iso(start);
    case "ytd":
      return `${today.getFullYear()}-01-01`;
    case "1y":
      start.setFullYear(start.getFullYear() - 1);
      return iso(start);
    case "5y":
      start.setFullYear(start.getFullYear() - 5);
      return iso(start);
    default:
      return null;
  }
}

/** Every ``step``-th value, always keeping the last one (light sparklines). */
export function thin<T>(values: readonly T[], target = 60): T[] {
  if (values.length <= target) return [...values];
  const step = Math.ceil(values.length / target);
  const kept = values.filter((_, index) => index % step === 0);
  const last = values[values.length - 1];
  if (last !== undefined && kept[kept.length - 1] !== last) kept.push(last);
  return kept;
}
