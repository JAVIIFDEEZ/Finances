"use client";

import { Plus, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";

import { CorrelationHeatmap, PriceChart, TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, Input, PageHeader, ProblemAlert, Refreshing, Segmented, Skeleton, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { isNotFound, useBars, useComparison, useFlow, useFunding, useQuality, useTechnical, type Interval } from "@/lib/api/queries";
import { rangeStart, type RangeKey } from "@/lib/util/dates";
import { perpetualOf } from "@/lib/util/instruments";
import { availableCharts, CHART_LINES, groupUnavailable, indicatorLabel, type Chart } from "@/lib/util/technical";
import { seriesColor } from "@/lib/theme/tokens";

const RANGES: readonly RangeKey[] = ["1m", "6m", "ytd", "1y", "5y", "max"];
const INTERVALS: readonly Interval[] = ["1d", "1w", "1mo"];

function useRangeOptions() {
  const { t } = useI18n();
  return RANGES.map((value) => ({ value, label: t(`range.${value}` as const) }));
}

function useIntervalOptions() {
  const { t } = useI18n();
  return INTERVALS.map((value) => ({ value, label: t(`interval.${value}` as "interval.1d") }));
}

function priceDigits(close: number | undefined): number {
  if (close === undefined) return 2;
  if (close < 10) return 4;
  if (close >= 10_000) return 0;
  return 2;
}

// ── One instrument ───────────────────────────────────────────────────

function InstrumentView({ symbol }: { symbol: string }) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const [range, setRange] = useState<RangeKey>("1y");
  const [interval, setInterval] = useState<Interval>("1d");
  const start = rangeStart(range);
  const bars = useBars(symbol, interval, start);
  const comparison = useComparison(useMemo(() => ({ symbols: [symbol], start, frequency: interval }), [symbol, start, interval]));
  const quality = useQuality(symbol, start);
  const series = bars.data;
  const metrics = comparison.data?.series[0]?.metrics;
  const drawdown = comparison.data?.series[0]?.drawdown ?? [];
  const lastClose = series?.bars[series.bars.length - 1]?.close;
  const digits = priceDigits(lastClose);
  const color = seriesColor(tokens, 0);
  const priceFormat = useMemo(() => (v: number) => fmt.number(v, digits), [fmt, digits]);
  const percentFormat = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);
  const rangeOptions = useRangeOptions();
  const intervalOptions = useIntervalOptions();
  const swap = perpetualOf(symbol);

  if (bars.isError && !series) {
    return (
      <div className="flex flex-col gap-3">
        <ProblemAlert error={bars.error} onRetry={() => void bars.refetch()} />
        <p className="text-text-2">{t("markets.notFound")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 rounded-lg border hairline bg-surface p-4 md:flex-row md:items-center md:justify-between">
        {series ? (
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-lg font-semibold tracking-tight text-text">{series.instrument.name}</h2>
              <span className="font-mono text-[13px] text-text-2">{series.instrument.symbol}</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge>{t(`asset.${series.instrument.asset_class}` as "asset.equity")}</Badge>
              <Badge>{series.instrument.currency}</Badge>
              {series.instrument.exchange ? <Badge>{series.instrument.exchange.name}</Badge> : null}
              <Badge tone="accent">
                {t("common.source")}: {series.source.provider}
              </Badge>
              <span className="text-xs text-muted">
                {t("common.updated")} {fmt.date(series.source.retrieved_at)}
              </span>
            </div>
          </div>
        ) : (
          <Skeleton className="h-12 w-72" />
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label={t("common.start")} value={range} options={rangeOptions} onChange={setRange} />
          <Segmented label={t("common.frequency")} value={interval} options={intervalOptions} onChange={setInterval} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <Card title={t("markets.price")} subtitle={series ? `${series.instrument.currency} · ${t("markets.adjustment")} ${t(`adjustment.${series.adjustment}` as "adjustment.raw")}` : undefined}>
          {series ? (
            <Refreshing active={bars.isFetching}>
              <PriceChart
                bars={series.bars.map((b) => ({ ...b, time: String(b.time) }))}
                format={priceFormat}
                color={color}
                label={`${t("markets.price")} ${series.instrument.symbol}`}
                labels={{
                  price: t("markets.price"),
                  volume: t("markets.volume"),
                  open: t("markets.open"),
                  high: t("markets.high"),
                  low: t("markets.low"),
                  close: t("markets.close"),
                }}
              />
            </Refreshing>
          ) : (
            <Skeleton className="h-[380px]" />
          )}
        </Card>

        <Card title={t("markets.stats")}>
          {series ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
              <Stat label={t("metric.lastClose")} value={fmt.number(lastClose, digits)} detail={series.instrument.currency} />
              <Stat label={t("metric.totalReturn")} value={fmt.signedPercent(series.stats.total_return)} />
              <Stat label={t("metric.cagr")} value={fmt.percent(series.stats.annualized_return)} />
              <Stat label={t("metric.volatility")} value={fmt.percent(series.stats.annualized_volatility)} />
              <Stat label={t("metric.maxDrawdown")} value={fmt.percent(series.stats.max_drawdown)} />
              <Stat
                label={t("metric.sharpe")}
                value={fmt.number(metrics?.sharpe_ratio, 2)}
                detail={metrics?.sharpe_standard_error != null ? `± ${fmt.number(metrics.sharpe_standard_error, 2)} ${t("metric.sharpeError")}` : undefined}
              />
              <Stat label={t("metric.sortino")} value={fmt.number(metrics?.sortino_ratio, 2)} />
              <Stat label={t("metric.var95")} value={fmt.percent(metrics?.tail.find((r) => r.level === 0.95 && r.method === "historical")?.value_at_risk ?? null, 2)} />
              <Stat label={t("metric.observations")} value={fmt.number(series.stats.n_observations, 0)} detail={`${fmt.date(series.stats.start)} – ${fmt.date(series.stats.end)}`} />
              <Stat label={t("metric.riskFree")} value={fmt.percent(metrics?.risk_free_rate ?? null, 2)} detail={metrics ? `${t("metric.riskFreeCoverage")}: ${fmt.percent(metrics.risk_free_coverage, 0)}` : undefined} />
            </dl>
          ) : (
            <Skeleton className="h-[300px]" />
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
        <Card title={t("markets.drawdown")}>
          {comparison.isError ? (
            <ProblemAlert error={comparison.error} onRetry={() => void comparison.refetch()} />
          ) : drawdown.length > 0 ? (
            <Refreshing active={comparison.isFetching}>
              <TimeSeriesChart
                height={220}
                label={t("markets.drawdown")}
                format={percentFormat}
                lines={[{ name: symbol, color, area: true, points: drawdown.map((p) => ({ time: String(p.time), value: p.value })) }]}
              />
            </Refreshing>
          ) : (
            <Skeleton className="h-[220px]" />
          )}
        </Card>
        <QualityCard quality={quality.data} loading={quality.isLoading} error={quality.isError ? quality.error : null} />
      </div>

      <TechnicalCard symbol={symbol} interval={interval} start={start} digits={digits} />

      <div className={swap ? "grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]" : "grid grid-cols-1 gap-6"}>
        <FlowCard symbol={symbol} interval={interval} start={start} color={color} />
        {swap ? <FundingCard swap={swap} start={start} color={color} /> : null}
      </div>
    </div>
  );
}

function TechnicalCard({ symbol, interval, start, digits }: { symbol: string; interval: Interval; start: string | null; digits: number }) {
  const { t, fmt, locale } = useI18n();
  const { tokens } = useTheme();
  const technical = useTechnical(symbol, interval, start);
  const data = technical.data;
  const charts = availableCharts(data?.indicators.map((indicator) => indicator.name) ?? []);
  const [picked, setPicked] = useState<Chart>("RSI");
  const chart = charts.includes(picked) ? picked : charts[0];
  const byName = new Map(data?.indicators.map((indicator) => [indicator.name, indicator]) ?? []);
  const oscillators = data?.indicators.filter((indicator) => indicator.kind === "oscillator") ?? [];
  const levels = data?.indicators.filter((indicator) => indicator.kind === "level") ?? [];
  const two = useMemo(() => (v: number) => fmt.number(v, 2), [fmt]);
  return (
    <Card title={t("markets.technical")} subtitle={t("markets.technicalNote")}>
      {technical.isLoading ? (
        <Skeleton className="h-[320px]" />
      ) : technical.isError ? (
        <ProblemAlert error={technical.error} onRetry={() => void technical.refetch()} />
      ) : data ? (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)]">
          <div className="flex min-w-0 flex-col gap-3">
            {chart ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Segmented label={t("markets.indicator")} value={chart} options={charts.map((value) => ({ value, label: value }))} onChange={setPicked} />
                </div>
                <Refreshing active={technical.isFetching}>
                  <TimeSeriesChart
                    height={220}
                    label={chart}
                    format={two}
                    lines={CHART_LINES[chart].map((name, index) => ({
                      name: indicatorLabel(name, byName.get(name)?.parameters ?? {}),
                      color: tokens.series[index] ?? tokens.text,
                      points: (byName.get(name)?.values ?? []).map((p) => ({ time: String(p.time), value: p.value })),
                    }))}
                  />
                </Refreshing>
              </>
            ) : null}
            {data.unavailable.length > 0 ? (
              <div className="flex flex-col gap-1 border-t hairline pt-3">
                <p className="text-xs font-medium text-text-2">{t("markets.unavailable")}</p>
                {groupUnavailable(data.unavailable).map((group) => (
                  <p key={group.missing.join()} className="text-xs text-muted">
                    {t("markets.needs")} {new Intl.ListFormat(locale, { type: "conjunction" }).format(group.missing.map((column) => t(`column.${column}`)))}: {group.names.join(", ")}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            {[
              { title: t("markets.oscillators"), rows: oscillators, places: 2 },
              { title: t("markets.levels"), rows: levels, places: digits },
            ].map((group) =>
              group.rows.length > 0 ? (
                <table key={group.title} className="w-full text-[13px]">
                  <caption className="mb-1 text-left text-xs font-medium text-text-2">{group.title}</caption>
                  <thead className="sr-only">
                    <tr>
                      <th scope="col">{t("markets.indicator")}</th>
                      <th scope="col">{t("markets.latest")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((indicator) => (
                      <tr key={indicator.name} className="border-t hairline">
                        <th scope="row" className="py-1.5 pr-3 text-left font-normal text-text-2">
                          <span className="font-mono text-[12px]">{indicatorLabel(indicator.name, indicator.parameters)}</span>
                        </th>
                        <td className="tabular py-1.5 text-right text-text">{fmt.number(indicator.latest, group.places)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null,
            )}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function signed(text: string, value: number | null | undefined): string {
  return value != null && value > 0 ? `+${text}` : text;
}

function FlowCard({ symbol, interval, start, color }: { symbol: string; interval: Interval; start: string | null; color: string }) {
  const { t, fmt } = useI18n();
  const flow = useFlow(symbol, interval, start);
  const compact = useMemo(() => (v: number) => fmt.compact(v), [fmt]);
  const data = flow.data;
  const aggressor = data?.has_aggressor_side ?? false;
  return (
    <Card title={t("markets.flow")} subtitle={data ? `${t("common.source")}: ${data.source.provider}` : undefined}>
      {flow.isLoading ? (
        <Skeleton className="h-[240px]" />
      ) : flow.isError && isNotFound(flow.error) ? (
        <p className="text-[13px] text-text-2">{t("markets.flowNone")}</p>
      ) : flow.isError ? (
        <ProblemAlert error={flow.error} onRetry={() => void flow.refetch()} />
      ) : data ? (
        <div className="flex flex-col gap-4">
          <Refreshing active={flow.isFetching}>
            <TimeSeriesChart
              height={220}
              label={aggressor ? t("markets.flowCvd") : t("markets.flowVolume")}
              format={compact}
              reference={aggressor ? 0 : undefined}
              lines={[
                {
                  name: aggressor ? "CVD" : t("markets.volume"),
                  color,
                  area: !aggressor,
                  points: data.bars.map((bar) => ({ time: String(bar.time), value: aggressor ? (bar.cvd ?? null) : bar.volume })),
                },
              ]}
            />
          </Refreshing>
          <p className="text-xs text-muted">{aggressor ? t("markets.flowCvd") : t("markets.flowNoAggressor")}</p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
            <Stat label={t("metric.totalVolume")} value={fmt.compact(data.summary.volume)} />
            <Stat label={t("metric.trades")} value={fmt.compact(data.summary.trades)} />
            <Stat label={t("metric.netDelta")} value={signed(fmt.compact(data.summary.delta), data.summary.delta)} />
            <Stat label={t("metric.buyRatio")} value={fmt.percent(data.summary.buy_ratio, 1)} />
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

function FundingCard({ swap, start, color }: { swap: string; start: string | null; color: string }) {
  const { t, fmt } = useI18n();
  const funding = useFunding(swap, start);
  const percent = useMemo(() => (v: number) => fmt.percent(v, 1), [fmt]);
  const data = funding.data;
  return (
    <Card title={t("markets.funding")} subtitle={data ? `${swap} · ${data.venue}` : swap}>
      {funding.isLoading ? (
        <Skeleton className="h-[240px]" />
      ) : funding.isError && isNotFound(funding.error) ? (
        <p className="text-[13px] text-text-2">{t("markets.fundingNone")}</p>
      ) : funding.isError ? (
        <ProblemAlert error={funding.error} onRetry={() => void funding.refetch()} />
      ) : data ? (
        <div className="flex flex-col gap-4">
          <Refreshing active={funding.isFetching}>
            <TimeSeriesChart
              height={180}
              label={t("markets.fundingRate")}
              format={percent}
              reference={0}
              lines={[{ name: t("markets.fundingRate"), color, points: data.rates.map((r) => ({ time: String(r.time), value: r.annualized })) }]}
            />
          </Refreshing>
          <p className="text-xs text-muted">{t("metric.fundingPayer")}</p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
            <Stat label={t("metric.fundingMean")} value={fmt.percent(data.summary.mean_annualized, 1)} />
            <Stat label={t("metric.fundingLong")} value={fmt.signedPercent(data.summary.accumulated_long, 2)} />
            <Stat label={t("metric.fundingPositive")} value={fmt.percent(data.summary.positive_share, 0)} />
            <Stat label={t("metric.fundingInterval")} value={`${fmt.number(data.interval_hours, 0)} h`} detail={`${fmt.number(data.summary.payments, 0)} ${t("metric.observations").toLowerCase()}`} />
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

function QualityCard({ quality, loading, error }: { quality: Schemas["QualityOut"] | undefined; loading: boolean; error: unknown }) {
  const { t, fmt } = useI18n();
  return (
    <Card title={t("markets.quality")}>
      {loading ? (
        <Skeleton className="h-[180px]" />
      ) : error ? (
        <ProblemAlert error={error} />
      ) : quality ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <Badge tone={quality.ok ? "good" : quality.worst_severity === "critical" ? "critical" : "warning"}>
              {quality.ok ? t("markets.qualityOk") : t("markets.qualityIssues")}
            </Badge>
            <span className="text-xs text-muted">
              {fmt.number(quality.observations, 0)} / {fmt.number(quality.expected_sessions ?? null, 0)} {t("markets.expectedSessions").toLowerCase()}
            </span>
          </div>
          {quality.issues.length > 0 ? (
            <ul className="flex flex-col gap-3">
              {quality.issues.map((issue) => (
                <li key={`${issue.kind}-${issue.message}`} className="flex flex-col gap-1 border-t hairline pt-3 first:border-0 first:pt-0">
                  <div className="flex items-center gap-2">
                    <Badge tone={issue.severity === "critical" ? "critical" : issue.severity === "warning" ? "warning" : "neutral"}>
                      {t(`markets.severity.${issue.severity}` as "markets.severity.info")}
                    </Badge>
                    <span className="font-mono text-[11px] text-muted">{issue.kind}</span>
                  </div>
                  <p className="text-[13px] text-text-2">{issue.message}</p>
                  {issue.examples.length > 0 ? (
                    <p className="text-xs text-muted">{issue.examples.slice(0, 4).map((d) => fmt.date(String(d))).join(" · ")}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

// ── Comparison ───────────────────────────────────────────────────────

interface Entry {
  symbol: string;
  slot: number;
}

const INITIAL: Entry[] = [
  { symbol: "SAN.MC", slot: 0 },
  { symbol: "BBVA.MC", slot: 1 },
  { symbol: "^IBEX", slot: 2 },
];

function CompareView() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const [entries, setEntries] = useState<Entry[]>(INITIAL);
  const [draft, setDraft] = useState("");
  const [range, setRange] = useState<RangeKey>("1y");
  const start = rangeStart(range);
  const request = useMemo(() => (entries.length > 0 ? { symbols: entries.map((e) => e.symbol), start } : null), [entries, start]);
  const comparison = useComparison(request);
  const colorOf = (symbol: string) => seriesColor(tokens, entries.find((e) => e.symbol === symbol)?.slot ?? 0);
  const percent = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);
  const level = useMemo(() => (v: number) => fmt.number(v, 0), [fmt]);
  const rangeOptions = useRangeOptions();

  const add = (event: FormEvent) => {
    event.preventDefault();
    const symbols = draft.split(/[\s,;]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
    setEntries((current) => {
      const next = [...current];
      for (const symbol of symbols) {
        if (next.some((e) => e.symbol === symbol) || next.length >= 8) continue;
        const used = new Set(next.map((e) => e.slot));
        let slot = 0;
        while (used.has(slot)) slot += 1;
        next.push({ symbol, slot });
      }
      return next;
    });
    setDraft("");
  };

  const series = comparison.data?.series ?? [];
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 rounded-lg border hairline bg-surface p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {entries.map((entry) => (
            <span key={entry.symbol} className="inline-flex h-8 items-center gap-2 rounded-md border hairline bg-surface-2 pl-2.5 pr-1 text-[13px]">
              <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: seriesColor(tokens, entry.slot) }} />
              <span className="font-mono text-text">{entry.symbol}</span>
              <button
                type="button"
                aria-label={`${t("portfolio.remove")} ${entry.symbol}`}
                className="grid size-6 place-items-center rounded text-muted hover:bg-surface-3 hover:text-text"
                onClick={() => setEntries((current) => current.filter((e) => e.symbol !== entry.symbol))}
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </span>
          ))}
          <form onSubmit={add} className="flex items-center gap-2">
            <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={t("markets.compareInput")} aria-label={t("markets.compareInput")} className="h-8 w-56" />
            <Button size="sm" type="submit" disabled={!draft.trim() || entries.length >= 8}>
              <Plus aria-hidden className="size-3.5" />
            </Button>
          </form>
        </div>
        <Segmented label={t("common.start")} value={range} options={rangeOptions} onChange={setRange} />
      </div>

      {entries.length === 0 ? (
        <p className="text-text-2">{t("empty.compare")}</p>
      ) : comparison.isError ? (
        <ProblemAlert error={comparison.error} onRetry={() => void comparison.refetch()} />
      ) : comparison.isLoading ? (
        <Skeleton className="h-[420px]" />
      ) : (
        <Refreshing active={comparison.isFetching}>
          <div className="flex flex-col gap-6">
            {comparison.data && comparison.data.failed.length > 0 ? (
              <div role="status" className="flex flex-wrap items-center gap-2 text-[13px] text-text-2">
                <Badge tone="warning">{t("markets.failed")}</Badge>
                {comparison.data.failed.map((f) => (
                  <span key={f.symbol} className="font-mono" title={f.reason}>
                    {f.symbol}
                  </span>
                ))}
              </div>
            ) : null}
            <Card title={t("markets.performance")}>
              <TimeSeriesChart
                height={340}
                reference={100}
                label={t("markets.performance")}
                format={level}
                lines={series.map((s) => ({ name: s.instrument.symbol, color: colorOf(s.instrument.symbol), points: s.performance.map((p) => ({ time: String(p.time), value: p.value })) }))}
              />
            </Card>
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]">
              <Card title={t("markets.drawdown")}>
                <TimeSeriesChart
                  height={260}
                  label={t("markets.drawdown")}
                  format={percent}
                  lines={series.map((s) => ({ name: s.instrument.symbol, color: colorOf(s.instrument.symbol), points: s.drawdown.map((p) => ({ time: String(p.time), value: p.value })) }))}
                />
              </Card>
              <Card title={t("markets.correlation")}>
                {comparison.data?.correlation ? (
                  <CorrelationHeatmap labels={comparison.data.correlation.labels} values={comparison.data.correlation.values} label={t("markets.correlation")} />
                ) : (
                  <p className="text-xs text-muted">—</p>
                )}
              </Card>
            </div>
            <Card title={t("markets.stats")} padded={false}>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="text-left text-xs text-text-2">
                    <tr className="border-b hairline">
                      <th className="px-4 py-2.5 font-medium">{t("common.symbol")}</th>
                      <th className="px-4 py-2.5 font-medium">{t("common.name")}</th>
                      <th className="px-4 py-2.5 text-right font-medium">{t("metric.totalReturn")}</th>
                      <th className="px-4 py-2.5 text-right font-medium">{t("metric.cagr")}</th>
                      <th className="px-4 py-2.5 text-right font-medium">{t("metric.volatility")}</th>
                      <th className="px-4 py-2.5 text-right font-medium">{t("metric.sharpe")}</th>
                      <th className="px-4 py-2.5 text-right font-medium">{t("metric.maxDrawdown")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series.map((s) => (
                      <tr key={s.instrument.symbol} className="border-b hairline last:border-0">
                        <td className="px-4 py-2.5">
                          <span className="inline-flex items-center gap-2 font-mono">
                            <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: colorOf(s.instrument.symbol) }} />
                            {s.instrument.symbol}
                          </span>
                        </td>
                        <td className="max-w-[240px] truncate px-4 py-2.5 text-text-2">{s.instrument.name}</td>
                        <td className="px-4 py-2.5 text-right">{fmt.signedPercent(s.metrics.total_return)}</td>
                        <td className="px-4 py-2.5 text-right">{fmt.percent(s.metrics.annualized_return)}</td>
                        <td className="px-4 py-2.5 text-right">{fmt.percent(s.metrics.annualized_volatility)}</td>
                        <td className="px-4 py-2.5 text-right">{fmt.number(s.metrics.sharpe_ratio, 2)}</td>
                        <td className="px-4 py-2.5 text-right">{fmt.percent(s.metrics.max_drawdown)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </Refreshing>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────

function MarketsContent() {
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const symbol = (params.get("symbol") ?? "SAN.MC").toUpperCase();
  const view = params.get("view") === "compare" ? "compare" : "explore";
  const setView = (next: "explore" | "compare") => {
    const query = new URLSearchParams(params.toString());
    query.set("view", next);
    router.replace(`${pathname}?${query.toString()}`);
  };
  return (
    <>
      <PageHeader
        title={t("markets.title")}
        subtitle={t("markets.subtitle")}
        actions={
          <Segmented
            label={t("markets.title")}
            value={view}
            onChange={setView}
            options={[
              { value: "explore", label: t("markets.tab.explore") },
              { value: "compare", label: t("markets.tab.compare") },
            ]}
          />
        }
      />
      {view === "compare" ? <CompareView /> : <InstrumentView key={symbol} symbol={symbol} />}
    </>
  );
}

export default function MarketsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[600px]" />}>
      <MarketsContent />
    </Suspense>
  );
}
