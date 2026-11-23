/** Locale-aware number and date formatting (never string concatenation of figures). */

import type { Locale } from "@/lib/i18n/messages";

const TAGS: Record<Locale, string> = { es: "es-ES", en: "en-GB" };

export interface Formatter {
  /** A decimal fraction as a percentage (`0.0523` → `5,2 %`). */
  percent(value: number | null | undefined, digits?: number): string;
  /** A signed percentage (`+5,2 %`). */
  signedPercent(value: number | null | undefined, digits?: number): string;
  /** A plain number. */
  number(value: number | null | undefined, digits?: number): string;
  /** A compact number (`12,9 mil`, `4,2 M`). */
  compact(value: number | null | undefined): string;
  /** An amount of money. */
  money(value: number | null | undefined, currency: string, digits?: number): string;
  /** A date (ISO `YYYY-MM-DD` or an instant). */
  date(value: string | Date | null | undefined): string;
  /** An instant with its local time to the second (`23 nov 2026, 12:48:05`). */
  dateTime(value: string | Date | null | undefined): string;
  /** How long ago, from a number of seconds, in the largest whole unit (`hace 5 min`). */
  ago(seconds: number | null | undefined): string;
  /** A short date for axes (`mar 24`). */
  monthYear(value: string | Date): string;
  /** The marks of a time axis: the year (`2026`), the short month (`nov`) and the day (`13`). */
  year(value: string | Date): string;
  month(value: string | Date): string;
  day(value: string | Date): string;
}

const DASH = "—";

/** The units of a relative time, from the largest, with their length in seconds. */
const AGO_UNITS: readonly (readonly [Intl.RelativeTimeFormatUnit, number])[] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || !Number.isFinite(value);
}

function asDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  // Session dates have no time: read them as calendar dates, not as UTC midnight.
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
}

export function formatter(locale: Locale): Formatter {
  const tag = TAGS[locale];
  const cache = new Map<string, Intl.NumberFormat>();
  const numberFormat = (key: string, options: Intl.NumberFormatOptions): Intl.NumberFormat => {
    let format = cache.get(key);
    if (!format) {
      format = new Intl.NumberFormat(tag, options);
      cache.set(key, format);
    }
    return format;
  };
  const dateFormat = new Intl.DateTimeFormat(tag, { year: "numeric", month: "short", day: "2-digit" });
  const dateTimeFormat = new Intl.DateTimeFormat(tag, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const relative = new Intl.RelativeTimeFormat(tag, { numeric: "always", style: "short" });
  const monthFormat = new Intl.DateTimeFormat(tag, { month: "short", year: "2-digit" });
  const yearOnly = new Intl.DateTimeFormat(tag, { year: "numeric" });
  const monthOnly = new Intl.DateTimeFormat(tag, { month: "short" });
  const dayOnly = new Intl.DateTimeFormat(tag, { day: "numeric" });

  return {
    percent(value, digits = 1) {
      if (isMissing(value)) return DASH;
      return numberFormat(`p${digits}`, {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);
    },
    signedPercent(value, digits = 1) {
      if (isMissing(value)) return DASH;
      return numberFormat(`sp${digits}`, {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
        signDisplay: "exceptZero",
      }).format(value);
    },
    number(value, digits = 2) {
      if (isMissing(value)) return DASH;
      return numberFormat(`n${digits}`, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);
    },
    compact(value) {
      if (isMissing(value)) return DASH;
      return numberFormat("c", { notation: "compact", maximumFractionDigits: 1 }).format(value);
    },
    money(value, currency, digits = 0) {
      if (isMissing(value)) return DASH;
      return numberFormat(`m${currency}${digits}`, {
        style: "currency",
        currency,
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(value);
    },
    date(value) {
      if (value === null || value === undefined) return DASH;
      return dateFormat.format(asDate(value));
    },
    dateTime(value) {
      if (value === null || value === undefined) return DASH;
      return dateTimeFormat.format(asDate(value));
    },
    ago(seconds) {
      if (isMissing(seconds)) return DASH;
      const elapsed = Math.max(0, seconds);
      for (const [unit, size] of AGO_UNITS) {
        if (elapsed >= size) return relative.format(-Math.floor(elapsed / size), unit);
      }
      return relative.format(-Math.floor(elapsed), "second");
    },
    monthYear(value) {
      return monthFormat.format(asDate(value));
    },
    year(value) {
      return yearOnly.format(asDate(value));
    },
    month(value) {
      return monthOnly.format(asDate(value));
    },
    day(value) {
      return dayOnly.format(asDate(value));
    },
  };
}
