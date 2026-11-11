import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";
import { AppShell } from "@/components/shell";
import { asLocale, asTheme, LOCALE_COOKIE, THEME_COOKIE } from "@/lib/preferences";

export const metadata: Metadata = {
  title: { default: "InvestingLab", template: "%s · InvestingLab" },
  description: "Market data, portfolio analytics, Monte Carlo simulation, optimisation and savings plans.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0d0d0d" },
    { media: "(prefers-color-scheme: light)", color: "#f9f9f7" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const preferences = await cookies();
  const theme = asTheme(preferences.get(THEME_COOKIE)?.value);
  const locale = asLocale(preferences.get(LOCALE_COOKIE)?.value);
  return (
    <html lang={locale} data-theme={theme}>
      <body>
        <Providers theme={theme} locale={locale}>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
