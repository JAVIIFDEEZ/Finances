"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { formatter, type Formatter } from "@/lib/i18n/format";
import { MESSAGES, type Locale, type MessageKey } from "@/lib/i18n/messages";
import { usePortfolio } from "@/lib/portfolio/store";
import { LOCALE_COOKIE, remember, THEME_COOKIE } from "@/lib/preferences";
import { TOKENS, type ChartTokens, type ThemeName } from "@/lib/theme/tokens";


// ── Theme ────────────────────────────────────────────────────────────

interface ThemeContextValue {
  theme: ThemeName;
  tokens: ChartTokens;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function ThemeProvider({ initial, children }: { initial: ThemeName; children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeName>(initial);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: ThemeName = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      remember(THEME_COOKIE, next);
      return next;
    });
  }, []);

  const value = useMemo(() => ({ theme, tokens: TOKENS[theme], toggle }), [theme, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme needs <Providers>");
  return context;
}

// ── Language ─────────────────────────────────────────────────────────

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey) => string;
  fmt: Formatter;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function I18nProvider({ initial, children }: { initial: Locale; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initial);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    remember(LOCALE_COOKIE, next);
  }, []);

  const value = useMemo<I18nContextValue>(() => {
    const messages = MESSAGES[locale];
    return { locale, setLocale, t: (key) => messages[key], fmt: formatter(locale) };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n needs <Providers>");
  return context;
}

// ── Data ─────────────────────────────────────────────────────────────

function retry(failures: number, error: unknown): boolean {
  // Problems the request itself causes (404, 422) never get better by retrying.
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failures < 2;
}

function RestoreDrafts() {
  useEffect(() => {
    void usePortfolio.persist.rehydrate();
  }, []);
  return null;
}

export function Providers({
  theme,
  locale,
  children,
}: {
  theme: ThemeName;
  locale: Locale;
  children: ReactNode;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider initial={theme}>
        <I18nProvider initial={locale}>
          <RestoreDrafts />
          {children}
        </I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
