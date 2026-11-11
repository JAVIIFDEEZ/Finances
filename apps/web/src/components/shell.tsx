"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import {
  BarChart3,
  Boxes,
  Compass,
  GraduationCap,
  LayoutDashboard,
  LineChart,
  Menu,
  Moon,
  PiggyBank,
  RotateCw,
  Search,
  Sun,
  Target,
  Unplug,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useI18n, useTheme } from "@/components/providers";
import { useQueryClient } from "@tanstack/react-query";

import { Button, cn, Segmented } from "@/components/ui";
import { failureOf } from "@/lib/api/client";
import { useHealth } from "@/lib/api/queries";
import type { MessageKey } from "@/lib/i18n/messages";

interface NavItem {
  href: string;
  label: MessageKey;
  icon: typeof LayoutDashboard;
}

const NAVIGATION: readonly { section: MessageKey | null; items: readonly NavItem[] }[] = [
  {
    section: null,
    items: [
      { href: "/", label: "nav.overview", icon: LayoutDashboard },
      { href: "/markets", label: "nav.markets", icon: LineChart },
    ],
  },
  {
    section: "nav.section.analysis",
    items: [
      { href: "/portfolio", label: "nav.portfolio", icon: Boxes },
      { href: "/simulation", label: "nav.simulation", icon: BarChart3 },
      { href: "/optimization", label: "nav.optimization", icon: Target },
      { href: "/planning", label: "nav.planning", icon: PiggyBank },
    ],
  },
  {
    section: "nav.section.platform",
    items: [{ href: "/modules", label: "nav.modules", icon: GraduationCap }],
  },
];

/** Instruments offered by the search before the user types (any symbol can be typed). */
export const UNIVERSE: readonly { symbol: string; name: string }[] = [
  { symbol: "^IBEX", name: "IBEX 35" },
  { symbol: "^GDAXI", name: "DAX" },
  { symbol: "^FCHI", name: "CAC 40" },
  { symbol: "^FTSE", name: "FTSE 100" },
  { symbol: "^GSPC", name: "S&P 500" },
  { symbol: "SAN.MC", name: "Banco Santander" },
  { symbol: "BBVA.MC", name: "BBVA" },
  { symbol: "ITX.MC", name: "Inditex" },
  { symbol: "IBE.MC", name: "Iberdrola" },
  { symbol: "TEF.MC", name: "Telefónica" },
  { symbol: "SAP.DE", name: "SAP" },
  { symbol: "ASML.AS", name: "ASML" },
  { symbol: "MC.PA", name: "LVMH" },
  { symbol: "AAPL", name: "Apple" },
  { symbol: "MSFT", name: "Microsoft" },
  { symbol: "NVDA", name: "NVIDIA" },
  { symbol: "SPY", name: "SPDR S&P 500 ETF" },
  { symbol: "EURUSD=X", name: "EUR/USD" },
  { symbol: "EURGBP=X", name: "EUR/GBP" },
  { symbol: "BTC-USD", name: "Bitcoin" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Brand() {
  const { t } = useI18n();
  return (
    <Link href="/" className="flex items-center gap-2.5 px-2 py-1">
      <span aria-hidden className="grid size-7 place-items-center rounded-md bg-accent text-on-accent">
        <Compass className="size-4" />
      </span>
      <span className="flex flex-col leading-none">
        <span className="text-[15px] font-semibold tracking-tight text-text">{t("app.name")}</span>
        <span className="mt-0.5 text-[11px] text-muted">{t("app.tagline")}</span>
      </span>
    </Link>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <nav aria-label={t("shell.menu")} className="flex flex-col gap-5">
      {NAVIGATION.map((group, index) => (
        <div key={group.section ?? index} className="flex flex-col gap-0.5">
          {group.section ? (
            <p className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">
              {t(group.section)}
            </p>
          ) : null}
          {group.items.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                  active ? "bg-accent-wash text-accent-strong" : "text-text-2 hover:bg-surface-2 hover:text-text",
                )}
              >
                <Icon aria-hidden className="size-4" />
                {t(item.label)}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function ApiStatus() {
  const { t } = useI18n();
  const health = useHealth();
  const online = health.isSuccess;
  const offline = health.data?.offline ?? false;
  const label = !online ? t("shell.api.offline") : offline ? t("shell.api.offlineMode") : t("shell.api.online");
  return (
    <div className="flex items-center gap-2 rounded-md border hairline bg-surface-2 px-2.5 py-1.5 text-xs text-text-2" title={health.data?.providers.join(" · ")}>
      <span
        aria-hidden
        className={cn("size-2 rounded-full", online ? (offline ? "bg-warning" : "bg-good") : health.isLoading ? "bg-muted" : "bg-critical")}
      />
      <span>{health.isLoading ? t("common.loading") : label}</span>
      {online && health.data ? <span className="hidden text-muted lg:inline">· {health.data.providers.join(", ")}</span> : null}
    </div>
  );
}

/**
 * One explanation when the API does not answer, instead of one in every card; when it
 * answers again, whatever failed meanwhile is fetched again.
 */
function ApiBanner() {
  const { t } = useI18n();
  const health = useHealth();
  const queryClient = useQueryClient();
  const wasDown = useRef(false);
  useEffect(() => {
    if (health.isError) {
      wasDown.current = true;
    } else if (health.isSuccess && wasDown.current) {
      wasDown.current = false;
      void queryClient.refetchQueries({ type: "active", predicate: (query) => query.state.status === "error" });
    }
  }, [health.isError, health.isSuccess, queryClient]);
  if (!health.isError || failureOf(health.error) !== "api") return null;
  return (
    <div
      role="alert"
      className="mb-6 flex items-start gap-3 rounded-lg border border-[color-mix(in_srgb,var(--critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--critical)_6%,var(--surface))] p-4"
    >
      <Unplug aria-hidden className="mt-0.5 size-4 shrink-0 text-critical-text" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-text">{t("shell.api.offline")}</p>
        <p className="mt-0.5 text-text-2">{t("error.network")}</p>
      </div>
      <Button size="sm" variant="ghost" onClick={() => void queryClient.invalidateQueries()}>
        <RotateCw aria-hidden className="size-3.5" />
        {t("common.retry")}
      </Button>
    </div>
  );
}

function SearchMenu() {
  const { t } = useI18n();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (symbol: string) => {
    setOpen(false);
    setQuery("");
    router.push(`/markets?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`);
  };
  const typed = query.trim();

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="flex h-9 w-full max-w-md items-center gap-2 rounded-md border hairline bg-surface-2 px-3 text-sm text-muted transition-colors hover:text-text-2"
        >
          <Search aria-hidden className="size-4" />
          <span className="flex-1 text-left">{t("shell.search")}</span>
          <kbd className="hidden rounded border hairline px-1.5 font-mono text-[11px] sm:inline">⌘K</kbd>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-[18%] z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-lg border hairline bg-surface shadow-2xl">
          <Dialog.Title className="sr-only">{t("shell.search")}</Dialog.Title>
          <Dialog.Description className="sr-only">{t("shell.searchHint")}</Dialog.Description>
          <Command label={t("shell.search")} shouldFilter>
            <div className="flex items-center gap-2 border-b hairline px-3">
              <Search aria-hidden className="size-4 text-muted" />
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder={t("shell.searchHint")}
                className="h-12 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-muted"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && typed && !UNIVERSE.some((u) => u.symbol === typed.toUpperCase())) {
                    event.preventDefault();
                    go(typed);
                  }
                }}
              />
            </div>
            <Command.List className="max-h-80 overflow-y-auto p-1.5">
              {typed ? (
                <Command.Item
                  value={`typed ${typed}`}
                  onSelect={() => go(typed)}
                  className="flex cursor-pointer items-center justify-between rounded-md px-2.5 py-2 text-sm text-text data-[selected=true]:bg-surface-2"
                >
                  <span className="font-mono">{typed.toUpperCase()}</span>
                  <span className="text-xs text-muted">↵</span>
                </Command.Item>
              ) : null}
              {UNIVERSE.map((item) => (
                <Command.Item
                  key={item.symbol}
                  value={`${item.symbol} ${item.name}`}
                  onSelect={() => go(item.symbol)}
                  className="flex cursor-pointer items-center justify-between rounded-md px-2.5 py-2 text-sm text-text data-[selected=true]:bg-surface-2"
                >
                  <span className="font-mono text-[13px]">{item.symbol}</span>
                  <span className="text-xs text-text-2">{item.name}</span>
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Preferences() {
  const { t, locale, setLocale } = useI18n();
  const { theme, toggle } = useTheme();
  return (
    <div className="flex items-center gap-2">
      <Segmented
        label={t("shell.language")}
        value={locale}
        onChange={setLocale}
        options={[
          { value: "es", label: "ES" },
          { value: "en", label: "EN" },
        ]}
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={theme === "dark" ? t("shell.theme.light") : t("shell.theme.dark")}
        title={theme === "dark" ? t("shell.theme.light") : t("shell.theme.dark")}
        className="grid size-9 place-items-center rounded-md border hairline bg-surface-2 text-text-2 hover:text-text"
      >
        {theme === "dark" ? <Sun aria-hidden className="size-4" /> : <Moon aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-dvh">
      <a href="#content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">
        {t("shell.skip")}
      </a>
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-r hairline bg-surface px-3 py-4 lg:flex">
        <Brand />
        <Navigation />
        <p className="mt-auto px-2 text-[11px] leading-relaxed text-muted">{t("footer.disclaimer")}</p>
      </aside>
      {open ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" aria-label={t("shell.menu")} className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="relative flex h-full w-64 flex-col gap-6 border-r hairline bg-surface px-3 py-4">
            <div className="flex items-center justify-between">
              <Brand />
              <button type="button" aria-label="Close" className="grid size-8 place-items-center text-text-2" onClick={() => setOpen(false)}>
                <X className="size-4" />
              </button>
            </div>
            <Navigation onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b hairline bg-[color-mix(in_srgb,var(--plane)_88%,transparent)] px-4 backdrop-blur md:px-6">
          <button
            type="button"
            aria-label={t("shell.menu")}
            className="grid size-9 place-items-center rounded-md border hairline bg-surface-2 text-text-2 lg:hidden"
            onClick={() => setOpen(true)}
          >
            <Menu aria-hidden className="size-4" />
          </button>
          <SearchMenu />
          <div className="ml-auto flex items-center gap-2">
            <div className="hidden md:block">
              <ApiStatus />
            </div>
            <Preferences />
          </div>
        </header>
        <main id="content" className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 md:px-6">
          <ApiBanner />
          {children}
        </main>
      </div>
    </div>
  );
}
