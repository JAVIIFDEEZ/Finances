"use client";

import { ArrowRight, Database, KeyRound } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { GroupedBars, Sparkline, TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, PageHeader, ProblemAlert, Segmented, Skeleton, Stat } from "@/components/ui";
import { failureOf } from "@/lib/api/client";
import { isNotFound, problemKind, useAnalytics, useBars, useEconomic, useHealth, useMarketCaps, useMarketSnapshot, useModules, useProviders, useRiskFree, useSources } from "@/lib/api/queries";
import { fill, type MessageKey } from "@/lib/i18n/messages";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { rangeStart, thin } from "@/lib/util/dates";
import { ageInMinutes, dominanceRows, shareOfTotal, sourceLabel } from "@/lib/util/marketReference";
import { secondsSince } from "@/lib/util/jobs";
import { fearGreedBand, isExtreme } from "@/lib/util/sentiment";
import { byProvider, dataAge, failingFor, sourceState, stateTone, type SourceState } from "@/lib/util/sources";

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

function FearGreedCard() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const start = useMemo(() => rangeStart("1y"), []);
  const index = useEconomic("FNG", start);
  const points = index.data?.observations ?? [];
  const values = points.map((p) => p.value);
  const latest = points[points.length - 1];
  const band = fearGreedBand(latest?.value);
  const recent = values.slice(-30);
  const average = recent.length > 0 ? recent.reduce((sum, v) => sum + v, 0) / recent.length : null;
  return (
    <Card title={t("overview.fearGreed")} subtitle={t("overview.fearGreedNote")}>
      {index.isLoading ? (
        <Skeleton className="h-[220px]" />
      ) : index.isError && isNotFound(index.error) ? (
        <p className="text-[13px] text-text-2">{t("overview.fearGreedNone")}</p>
      ) : index.isError ? (
        <ProblemAlert error={index.error} onRetry={() => void index.refetch()} />
      ) : latest ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
            <Stat label={fmt.date(latest.time)} value={fmt.number(latest.value, 0)} />
            {band ? <Badge tone={isExtreme(band) ? "warning" : "neutral"}>{t(`sentiment.${band}`)}</Badge> : null}
          </div>
          <TimeSeriesChart
            height={150}
            label={t("overview.fearGreed")}
            format={(v) => fmt.number(v, 0)}
            reference={50}
            lines={[{ name: "Fear & Greed", color: tokens.series[1] ?? tokens.text, points: points.map((p) => ({ time: String(p.time), value: p.value })) }]}
          />
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
            <Stat label={t("metric.average30")} value={fmt.number(average, 0)} />
            <Stat label={t("metric.yearRange")} value={values.length > 0 ? `${fmt.number(Math.min(...values), 0)} – ${fmt.number(Math.max(...values), 0)}` : "—"} />
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

const MARKET_CURRENCIES = ["USD", "EUR"] as const;
type MarketCurrency = (typeof MARKET_CURRENCIES)[number];
const MARKET_TOP = 10;

function CryptoMarketCard() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const [currency, setCurrency] = useState<MarketCurrency>("USD");
  const snapshot = useMarketSnapshot(currency);
  const caps = useMarketCaps(currency, MARKET_TOP);
  const data = snapshot.data;
  const percent = useMemo(() => (v: number) => fmt.percent(v, 1), [fmt]);
  const ticks = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);
  const rows = data ? dominanceRows(data, t("market.others")) : [];
  return (
    <Card
      className="xl:col-span-2"
      title={t("market.title")}
      subtitle={data ? fill(t("market.asOf"), { source: sourceLabel(data.source.provider), minutes: ageInMinutes(data.as_of) }) : t("market.note")}
      actions={<Segmented label={t("market.currency")} value={currency} onChange={setCurrency} options={MARKET_CURRENCIES.map((value) => ({ value, label: value }))} />}
    >
      {snapshot.isLoading ? (
        <Skeleton className="h-[260px]" />
      ) : snapshot.isError && isNotFound(snapshot.error) ? (
        <p className="text-[13px] text-text-2">{t("market.none")}</p>
      ) : snapshot.isError ? (
        <ProblemAlert error={snapshot.error} onRetry={() => void snapshot.refetch()} />
      ) : data ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-4">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
              <Stat label={t("market.total")} value={`${fmt.compact(data.total_market_cap)} ${data.currency}`} />
              <Stat
                label={t("market.change24h")}
                value={fmt.signedPercent(data.market_cap_change_24h, 1)}
                detail={data.market_cap_change_24h === null ? t("market.changeUsdOnly") : undefined}
              />
              <Stat label={t("market.volume24h")} value={data.total_volume_24h === null ? "—" : `${fmt.compact(data.total_volume_24h)} ${data.currency}`} />
              <Stat label={t("market.assets")} value={fmt.number(data.assets, 0)} />
            </dl>
            <p className="text-xs font-medium text-text-2">{t("market.dominance")}</p>
            <GroupedBars
              label={t("market.dominance")}
              categories={rows.map((row) => row.label)}
              series={[{ name: t("market.share"), color: tokens.series[0] ?? tokens.text, values: rows.map((row) => row.share) }]}
              format={percent}
              axisFormat={ticks}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-3">
            {caps.isError && !isNotFound(caps.error) ? <ProblemAlert error={caps.error} onRetry={() => void caps.refetch()} /> : null}
            {caps.data ? (
              <table className="w-full text-[13px]">
                <caption className="sr-only">{t("market.ranking")}</caption>
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th scope="col" className="w-7 py-1 pr-2 font-medium">#</th>
                    <th scope="col" className="w-full py-1 font-medium">{t("market.asset")}</th>
                    <th scope="col" className="whitespace-nowrap py-1 pl-3 text-right font-medium">{fill(t("market.price"), { currency: caps.data.currency })}</th>
                    <th scope="col" className="whitespace-nowrap py-1 pl-3 text-right font-medium">{t("market.cap")}</th>
                    <th scope="col" className="whitespace-nowrap py-1 pl-3 text-right font-medium">{t("market.share")}</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {caps.data.assets.map((asset) => (
                    <tr key={asset.id} className="border-t hairline">
                      <td className="py-1.5 pr-2 text-muted">{asset.rank}</td>
                      <th scope="row" className="max-w-0 py-1.5 text-left font-medium">
                        <span className="block truncate">{asset.symbol}</span>
                        <span className="block truncate text-xs font-normal text-muted">{asset.name}</span>
                      </th>
                      <td className="whitespace-nowrap py-1.5 pl-3 text-right">{fmt.number(asset.price, asset.price !== null && asset.price < 10 ? 4 : 2)}</td>
                      <td className="whitespace-nowrap py-1.5 pl-3 text-right">{fmt.compact(asset.market_cap)}</td>
                      <td className="whitespace-nowrap py-1.5 pl-3 text-right">{fmt.percent(shareOfTotal(asset.market_cap, data.total_market_cap), 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : caps.isLoading ? (
              <Skeleton className="h-[260px]" />
            ) : null}
            <p className="text-xs text-muted">{t("market.note")}</p>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

const SOURCE_BADGE = {
  ok: "overview.sources.badge.ok",
  failing: "overview.sources.badge.failing",
  stale: "overview.sources.badge.stale",
  unchecked: "overview.sources.badge.unchecked",
} as const satisfies Record<Exclude<SourceState["kind"], "local">, MessageKey>;

/** What the worker last saw of a source: how it answered, since when it fails, or nothing yet. */
function SourceDetail({ state }: { state: SourceState }) {
  const { t, fmt } = useI18n();
  switch (state.kind) {
    case "ok":
      return (
        <p className="text-xs text-text-2 tabular">
          {fill(t("overview.sources.ok"), {
            latency: fmt.number(state.status.latency_seconds, 2),
            age: fmt.ago(dataAge(state.status)),
          })}
        </p>
      );
    case "failing": {
      const since = failingFor(state.status);
      return (
        <>
          <p className="text-xs text-critical-text tabular">
            {fill(t("overview.sources.failing"), { count: state.status.failures })}
            {" · "}
            {since === null ? t("overview.sources.neverAnswered") : fill(t("overview.sources.lastAnswered"), { when: fmt.ago(since) })}
          </p>
          {state.status.error ? (
            <p className="truncate font-mono text-[11px] text-muted" title={state.status.error}>
              {state.status.error}
            </p>
          ) : null}
        </>
      );
    }
    case "stale":
      return (
        <p className="text-xs text-text-2 tabular">
          {fill(t("overview.sources.stale"), { when: fmt.ago(secondsSince(state.status.checked_at)) })}
        </p>
      );
    case "unchecked":
      return <p className="text-xs text-text-2">{t("overview.sources.unchecked")}</p>;
    default:
      return <p className="text-xs text-text-2">{t("overview.sources.local")}</p>;
  }
}

function ProvidersCard() {
  const { t } = useI18n();
  const providers = useProviders();
  const health = useHealth();
  const sources = useSources();
  const statuses = byProvider(sources.data);
  return (
    <Card title={t("overview.providers")} subtitle={t("overview.providersNote")}>
      {providers.isLoading ? (
        <Skeleton className="h-[160px]" />
      ) : providers.isError ? (
        <ProblemAlert error={providers.error} onRetry={() => void providers.refetch()} />
      ) : (
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {providers.data?.map((provider, index) => {
            // Only with a database does the worker keep what it saw of each source.
            const state = sources.isSuccess ? sourceState(provider, statuses.get(provider.name)) : null;
            return (
              <li key={provider.name} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                <span className="grid size-7 shrink-0 place-items-center rounded-md bg-surface-2 font-mono text-[11px] text-text-2">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 font-medium text-text">
                    {provider.name}
                    {state && provider.requires_api_key ? (
                      <KeyRound role="img" aria-label={t("overview.requiresKey")} className="size-3 text-muted" />
                    ) : null}
                  </p>
                  <p className="truncate text-xs text-muted">
                    {provider.datasets.join(" · ")} · {provider.asset_classes.length > 6 ? "multi-asset" : provider.asset_classes.join(", ")} · {provider.frequencies[0]}–{provider.frequencies[provider.frequencies.length - 1]}
                  </p>
                  {state ? <SourceDetail state={state} /> : null}
                </div>
                {state && state.kind !== "local" ? (
                  <Badge tone={stateTone(state)}>{t(SOURCE_BADGE[state.kind])}</Badge>
                ) : provider.requires_api_key ? (
                  <Badge tone="warning">
                    <KeyRound aria-hidden className="size-3" /> {t("overview.requiresKey")}
                  </Badge>
                ) : (
                  <Badge tone="good">{t("overview.noKey")}</Badge>
                )}
              </li>
            );
          })}
          {sources.isError ? (
            <li className="pt-2.5 text-xs text-muted">
              {t(problemKind(sources.error) === "persistence-not-configured" ? "overview.sources.noDatabase" : "overview.sources.unavailable")}
            </li>
          ) : null}
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
            <Database aria-hidden className="size-3" /> Yahoo Finance · BCE · Binance · OKX · CoinGecko
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
        <FearGreedCard />
        <CryptoMarketCard />
        <ProvidersCard />
        <ModulesCard />
      </div>
    </>
  );
}
