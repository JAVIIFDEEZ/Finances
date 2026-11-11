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
  /** A short date for axes (`mar 24`). */
  monthYear(value: string | Date): string;
}

const DASH = "—";

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
  const monthFormat = new Intl.DateTimeFormat(tag, { month: "short", year: "2-digit" });

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
    monthYear(value) {
      return monthFormat.format(asDate(value));
    },
  };
}
