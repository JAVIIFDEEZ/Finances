"use client";

import { ArrowRight, Database, KeyRound } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Sparkline, TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, PageHeader, ProblemAlert, Skeleton, Stat } from "@/components/ui";
import { failureOf } from "@/lib/api/client";
import { useAnalytics, useBars, useHealth, useModules, useProviders, useRiskFree } from "@/lib/api/queries";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { rangeStart, thin } from "@/lib/util/dates";

const WATCHLIST: readonly { symbol: string; name: string; digits: number }[] = [
  { symbol: "^IBEX", name: "IBEX 35", digits: 0 },
  { symbol: "^GDAXI", name: "DAX", digits: 0 },
  { symbol: "^GSPC", name: "S&P 500", digits: 0 },
  { symbol: "EURUSD=X", name: "EUR/USD", digits: 4 },
  { symbol: "BTC-USD", name: "Bitcoin", digits: 0 },
];

function WatchTile({ symbol, name, digits }: { symbol: string; name: string; digits: number }) {
  const { t, fmt } = useI18n();
  const start = useMemo(() => rangeStart("1y"), []);
  const bars = useBars(symbol, "1d", start);
  const closes = bars.data?.bars.map((b) => b.close) ?? [];
  const last = closes[closes.length - 1];
  const previous = closes[closes.length - 2];
  const first = closes[0];
  const daily = last !== undefined && previous ? last / previous - 1 : null;
  const yearly = last !== undefined && first ? last / first - 1 : null;
  return (
    <Link
      href={`/markets?symbol=${encodeURIComponent(symbol)}`}
      className="group flex min-w-0 flex-col gap-2 rounded-lg border hairline bg-surface p-4 transition-colors hover:border-border-strong"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13px] font-medium text-text">{name}</span>
        <span className="font-mono text-[11px] text-muted">{symbol}</span>
      </div>
      {bars.isLoading ? (
        <Skeleton className="h-[86px]" />
      ) : bars.isError ? (
        <p className="text-xs text-muted">{t(failureOf(bars.error) === "api" ? "error.apiShort" : "error.unavailable")}</p>
      ) : (
        <>
          <div className="flex items-end justify-between gap-2">
            <span className="text-xl font-semibold tracking-tight text-text">{fmt.number(last, digits)}</span>
            <span className={daily === null ? "text-xs text-muted" : daily >= 0 ? "text-xs font-medium text-good-text" : "text-xs font-medium text-critical-text"}>
              {daily === null ? "—" : `${daily >= 0 ? "▲" : "▼"} ${fmt.signedPercent(daily, 2)}`}
            </span>
          </div>
          <Sparkline values={thin(closes, 64)} label={`${name}: ${fmt.signedPercent(yearly)}`} height={40} />
          <div className="flex justify-between text-[11px] text-muted">
            <span>{t("range.1y")}</span>
            <span className="tabular">{fmt.signedPercent(yearly)}</span>
          </div>
        </>
      )}
    </Link>
  );
}

function RiskFreeCard() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const start = useMemo(() => rangeStart("1y") ?? "2025-01-01", []);
  const rates = useRiskFree("EUR", start);
  const points = rates.data?.rates.filter((p) => p.value !== null) ?? [];
  const latest = points[points.length - 1];
  const yearAgo = points[0];
  const change = latest?.value != null && yearAgo?.value != null ? latest.value - yearAgo.value : null;
  return (
    <Card title={t("overview.riskFree")} subtitle={t("overview.riskFreeNote")}>
      {rates.isLoading ? (
        <Skeleton className="h-[220px]" />
      ) : rates.isError ? (
        <ProblemAlert error={rates.error} onRetry={() => void rates.refetch()} />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex gap-8">
            <Stat label={fmt.date(latest?.time)} value={fmt.percent(latest?.value ?? null, 2)} />
            <Stat
              label={t("range.1y")}
              value={change === null ? "—" : `${change >= 0 ? "+" : "−"}${fmt.number(Math.abs(change) * 10_000, 0)} ${t("unit.bp")}`}
            />
          </div>
          <TimeSeriesChart
            height={170}
            label={t("overview.riskFree")}
            format={(v) => fmt.percent(v, 2)}
            lines={[{ name: "€STR", color: tokens.series[0] ?? tokens.text, area: true, points: points.map((p) => ({ time: String(p.time), value: p.value })) }]}
          />
        </div>
      )}
    </Card>
  );
}

function ProvidersCard() {
  const { t } = useI18n();
  const providers = useProviders();
  const health = useHealth();
  return (
    <Card title={t("overview.providers")} subtitle={t("overview.providersNote")}>
      {providers.isLoading ? (
        <Skeleton className="h-[160px]" />
      ) : providers.isError ? (
        <ProblemAlert error={providers.error} onRetry={() => void providers.refetch()} />
      ) : (
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {providers.data?.map((provider, index) => (
            <li key={provider.name} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <span className="grid size-7 shrink-0 place-items-center rounded-md bg-surface-2 font-mono text-[11px] text-text-2">{index + 1}</span>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-text">{provider.name}</p>
                <p className="truncate text-xs text-muted">
                  {provider.datasets.join(" · ")} · {provider.asset_classes.length > 6 ? "multi-asset" : provider.asset_classes.join(", ")} · {provider.frequencies[0]}–{provider.frequencies[provider.frequencies.length - 1]}
                </p>
              </div>
              {provider.requires_api_key ? (
                <Badge tone="warning">
                  <KeyRound aria-hidden className="size-3" /> {t("overview.requiresKey")}
                </Badge>
              ) : (
                <Badge tone="good">{t("overview.noKey")}</Badge>
              )}
            </li>
          ))}
          {health.data?.offline ? (
            <li className="pt-2.5">
              <Badge tone="warning">{t("shell.api.offlineMode")}</Badge>
            </li>
          ) : null}
        </ul>
      )}
    </Card>
  );
}

function ModulesCard() {
  const { t, locale } = useI18n();
  const modules = useModules(locale);
  return (
    <Card title={t("overview.modules")} actions={<Link href="/modules" className="text-xs font-medium text-accent hover:underline">{t("nav.modules")}</Link>}>
      {modules.isLoading ? (
        <Skeleton className="h-[120px]" />
      ) : modules.isError ? (
        <ProblemAlert error={modules.error} onRetry={() => void modules.refetch()} />
      ) : (
        <ul className="flex flex-col gap-4">
          {modules.data?.map((module) => {
            const total = module.requirements.length;
            const done = module.requirements.filter((r) => r.status === "done").length;
            const partial = module.requirements.filter((r) => r.status === "partial").length;
            return (
              <li key={module.slug} className="flex flex-col gap-2">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-text">{module.title}</span>
                  <span className="tabular text-xs text-text-2">
                    {done}/{total} {t("modules.status.done").toLowerCase()}
                  </span>
                </div>
                <div className="flex h-2 gap-[2px] overflow-hidden rounded-full" role="img" aria-label={`${done} / ${total}`}>
                  <span className="rounded-full bg-good" style={{ flexGrow: done }} />
                  {partial > 0 ? <span className="rounded-full bg-warning" style={{ flexGrow: partial }} /> : null}
                  {total - done - partial > 0 ? <span className="rounded-full bg-surface-3" style={{ flexGrow: total - done - partial }} /> : null}
                </div>
                <p className="text-xs text-muted">{module.block}</p>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function PortfolioCard() {
  const { t, fmt } = useI18n();
  const draft = usePortfolio((state) => state.draft);
  const request = useMemo(() => toPortfolioIn(draft), [draft]);
  const analytics = useAnalytics(request);
  const metrics = analytics.data?.metrics;
  return (
    <Card
      title={t("overview.portfolio")}
      subtitle={draft.name}
      actions={
        <Link href="/portfolio">
          <Button size="sm" variant="primary">
            {t("overview.portfolioCta")} <ArrowRight aria-hidden className="size-3.5" />
          </Button>
        </Link>
      }
    >
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_2fr]">
        <ul className="flex flex-col gap-1.5">
          {draft.holdings.map((holding) => (
            <li key={holding.symbol} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="font-mono text-text">{holding.symbol}</span>
              <span className="tabular text-text-2">{fmt.percent(holding.weight / 100, 1)}</span>
            </li>
          ))}
        </ul>
        {analytics.isLoading ? (
          <Skeleton className="h-[96px]" />
        ) : analytics.isError ? (
          <ProblemAlert error={analytics.error} onRetry={() => void analytics.refetch()} />
        ) : metrics ? (
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label={t("metric.cagr")} value={fmt.percent(metrics.annualized_return)} />
            <Stat label={t("metric.volatility")} value={fmt.percent(metrics.annualized_volatility)} />
            <Stat label={t("metric.sharpe")} value={fmt.number(metrics.sharpe_ratio, 2)} />
            <Stat label={t("metric.maxDrawdown")} value={fmt.percent(metrics.max_drawdown)} />
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export default function OverviewPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader
        title={t("overview.title")}
        subtitle={t("overview.subtitle")}
        actions={
          <Badge tone="accent">
            <Database aria-hidden className="size-3" /> Yahoo Finance · BCE
          </Badge>
        }
      />
      <section aria-label={t("overview.watchlist")} className="mb-6">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-[13px] font-semibold uppercase tracking-[0.04em] text-text-2">{t("overview.watchlist")}</h2>
          <span className="text-xs text-muted">{t("overview.watchlistNote")}</span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {WATCHLIST.map((item) => (
            <WatchTile key={item.symbol} {...item} />
          ))}
        </div>
      </section>
      <div className="mb-6">
        <PortfolioCard />
      </div>
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-3">
        <div className="xl:col-span-1">
          <RiskFreeCard />
        </div>
        <ProvidersCard />
        <ModulesCard />
      </div>
    </>
  );
}
