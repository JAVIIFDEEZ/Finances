/** Interface preferences kept in cookies, so the server renders them from the first byte. */

import { LOCALES, type Locale } from "@/lib/i18n/messages";
import type { ThemeName } from "@/lib/theme/tokens";

export const THEME_COOKIE = "investinglab.theme";
export const LOCALE_COOKIE = "investinglab.locale";

/** The supported locale named by ``value``, or Spanish. */
export function asLocale(value: string | undefined): Locale {
  return (LOCALES as readonly string[]).includes(value ?? "") ? (value as Locale) : "es";
}

/** The theme named by ``value``; dark (the terminal look) by default. */
export function asTheme(value: string | undefined): ThemeName {
  return value === "light" ? "light" : "dark";
}

/** Store a preference for a year (client side). */
export function remember(name: string, value: string): void {
  document.cookie = `${name}=${value}; path=/; max-age=31536000; samesite=lax`;
}
