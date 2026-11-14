"use client";

import { Plus, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useMemo, useState, type FormEvent } from "react";

import { CorrelationHeatmap, PriceChart, TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, Input, PageHeader, ProblemAlert, Refreshing, Segmented, Skeleton, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { isNotFound, useBars, useComparison, useFlow, useFunding, usePatterns, useQuality, useStructure, useTechnical, type Interval } from "@/lib/api/queries";
import { isMessageKey } from "@/lib/i18n/messages";
import { rangeStart, type RangeKey } from "@/lib/util/dates";
import { perpetualOf } from "@/lib/util/instruments";
import { byFamily, occurrences, recentEvents, type Direction } from "@/lib/util/patterns";
import { availableOverlays, groupUnavailable, indicatorLabel, OVERLAYS, type Overlay } from "@/lib/util/technical";
import { StructureCard } from "@/components/markets/structure";
import { TechnicalCard, TechnicalSummary } from "@/components/markets/technical";
import type { PriceLevel, PriceOverlay } from "@/components/charts/charts";
import { seriesColor } from "@/lib/theme/tokens";

const RANGES: readonly RangeKey[] = ["1m", "6m", "ytd", "1y", "5y", "max"];
const INTERVALS: readonly Interval[] = ["1d", "1w", "1mo"];

/** What can be drawn over the prices: indicator lines, the structure's levels, Fibonacci. */
type OverlayChoice = Overlay | "levels" | "fibonacci";

/** The palette slot of each line of each overlay (fixed: a colour always means the same line). */
const OVERLAY_COLOURS: Record<Overlay, readonly number[]> = {
  averages: [1, 2],
  bollinger: [3, 3],
  keltner: [5, 5],
  ichimoku: [4, 6],
  sar: [0],
};

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
  const patterns = usePatterns(symbol, interval, start);
  const technical = useTechnical(symbol, interval, start);
  const structure = useStructure(symbol, interval, start);
  const patternLabel = usePatternLabel();
  const [shownOverlays, setShownOverlays] = useState<ReadonlySet<OverlayChoice>>(() => new Set(["averages"]));
  const toggleOverlay = (choice: OverlayChoice) =>
    setShownOverlays((shown) => {
      const next = new Set(shown);
      if (next.has(choice)) next.delete(choice);
      else next.add(choice);
      return next;
    });
  const overlayChoices = useMemo<OverlayChoice[]>(() => {
    const lines = availableOverlays(technical.data?.indicators.map((i) => i.name) ?? []);
    const levels: OverlayChoice[] = (structure.data?.levels.length ?? 0) > 0 ? ["levels"] : [];
    const fibonacci: OverlayChoice[] = (structure.data?.fibonacci?.levels.length ?? 0) > 0 ? ["fibonacci"] : [];
    return [...lines, ...levels, ...fibonacci];
  }, [technical.data, structure.data]);
  const overlayColor = useCallback(
    (overlay: Overlay, index: number) => tokens.series[OVERLAY_COLOURS[overlay][index] ?? 0] ?? tokens.text,
    [tokens],
  );
  const priceOverlays = useMemo<PriceOverlay[]>(() => {
    const byName = new Map(technical.data?.indicators.map((i) => [i.name, i]) ?? []);
    return availableOverlays([...byName.keys()])
      .filter((overlay) => shownOverlays.has(overlay))
      .flatMap((overlay) =>
        OVERLAYS[overlay].lines.flatMap((line, index) => {
          const indicator = byName.get(line);
          if (!indicator) return [];
          return [
            {
              name: indicatorLabel(line, indicator.parameters),
              color: overlayColor(overlay, index),
              style: OVERLAYS[overlay].style,
              values: new Map(indicator.values.map((p) => [String(p.time), p.value])),
            },
          ];
        }),
      );
  }, [technical.data, shownOverlays, overlayColor]);
  const priceLevels = useMemo<PriceLevel[]>(() => {
    const found: PriceLevel[] = [];
    if (shownOverlays.has("levels")) {
      // Only the nearest support and resistance are labelled: eight labels would overlap.
      const nearest = new Set([structure.data?.nearest_support, structure.data?.nearest_resistance]);
      for (const level of structure.data?.levels ?? []) {
        found.push({
          price: level.price,
          color: level.kind === "support" ? tokens.up : tokens.down,
          label: nearest.has(level.price) ? `${t(level.kind === "support" ? "markets.supportShort" : "markets.resistanceShort")} ${fmt.number(level.price, digits)}` : "",
        });
      }
    }
    if (shownOverlays.has("fibonacci")) {
      for (const level of structure.data?.fibonacci?.levels ?? []) {
        found.push({ price: level.price, color: tokens.muted, label: fmt.percent(level.ratio, 1) });
      }
    }
    return found;
  }, [structure.data, shownOverlays, tokens, t, fmt, digits]);
  const [shown, setShown] = useState<string | null>(null);
  const shownPattern = patterns.data?.patterns.find((p) => p.name === shown);
  const priceEvents = useMemo(
    () => occurrences(patterns.data?.events ?? [], shownPattern).map((o) => ({ ...o, label: patternLabel(shownPattern?.name ?? "") })),
    [patterns.data, shownPattern, patternLabel],
  );

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
        <Card
          title={t("markets.price")}
          subtitle={series ? `${series.instrument.currency} · ${t("markets.adjustment")} ${t(`adjustment.${series.adjustment}` as "adjustment.raw")}` : undefined}
          actions={
            overlayChoices.length > 0 ? (
              <div role="group" aria-label={t("markets.overlays")} className="flex flex-wrap items-center gap-1">
                {overlayChoices.map((choice) => (
                  <Button
                    key={choice}
                    size="sm"
                    variant="ghost"
                    aria-pressed={shownOverlays.has(choice)}
                    onClick={() => toggleOverlay(choice)}
                    className="gap-1.5 border hairline aria-pressed:bg-accent-wash aria-pressed:text-text"
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-0.5 w-3 rounded-full"
                      style={{
                        background:
                          choice === "levels" ? `linear-gradient(90deg, ${tokens.up} 50%, ${tokens.down} 50%)` : choice === "fibonacci" ? tokens.muted : overlayColor(choice, 0),
                      }}
                    />
                    {t(`overlay.${choice}`)}
                  </Button>
                ))}
              </div>
            ) : undefined
          }
        >
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
                events={priceEvents}
                overlays={priceOverlays}
                levels={priceLevels}
              />
            </Refreshing>
          ) : (
            <Skeleton className="h-[380px]" />
          )}
          {shownPattern ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-2">
              <span>
                {t("markets.onChart")}: <strong className="font-medium text-text">{patternLabel(shownPattern.name)}</strong> ({fmt.number(priceEvents.length, 0)})
              </span>
              <Button size="sm" variant="ghost" onClick={() => setShown(null)}>
                <X className="size-3.5" aria-hidden="true" />
                {t("markets.hide")}
              </Button>
            </div>
          ) : null}
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

      <TechnicalSummary query={technical} />

      <TechnicalCard query={technical} digits={digits} />

      <StructureCard query={structure} digits={digits} />

      <PatternsCard query={patterns} shown={shown} onShow={setShown} />

      <div className={swap ? "grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]" : "grid grid-cols-1 gap-6"}>
        <FlowCard symbol={symbol} interval={interval} start={start} color={color} />
        {swap ? <FundingCard swap={swap} start={start} color={color} /> : null}
      </div>
    </div>
  );
}

/** A pattern's name in the interface language (its catalogue name if the web does not know it). */
function usePatternLabel(): (name: string) => string {
  const { t } = useI18n();
  return useCallback(
    (name: string) => {
      const key = `pattern.${name}`;
      return isMessageKey(key) ? t(key) : name;
    },
    [t],
  );
}

/** The direction of a pattern's definition: shape and colour together, and named for readers. */
function DirectionMark({ direction }: { direction: Direction }) {
  const { t } = useI18n();
  const { tokens } = useTheme();
  const color = direction === "bullish" ? tokens.up : direction === "bearish" ? tokens.down : tokens.muted;
  return (
    <>
      <span aria-hidden="true" className="w-3 shrink-0 text-center text-[10px]" style={{ color }}>
        {direction === "bullish" ? "▲" : direction === "bearish" ? "▼" : "◆"}
      </span>
      <span className="sr-only">{t(`direction.${direction}`)}</span>
    </>
  );
}

function PatternsCard({
  query,
  shown,
  onShow,
}: {
  query: ReturnType<typeof usePatterns>;
  shown: string | null;
  onShow: (name: string | null) => void;
}) {
  const { t, fmt, locale } = useI18n();
  const label = usePatternLabel();
  const data = query.data;
  const latest = data ? recentEvents(data.events, 8) : [];
  return (
    <Card title={t("markets.patterns")} subtitle={t("markets.patternsNote")}>
      {query.isLoading ? (
        <Skeleton className="h-[240px]" />
      ) : query.isError ? (
        <ProblemAlert error={query.error} onRetry={() => void query.refetch()} />
      ) : data ? (
        <div className="flex flex-col gap-5">
          {data.patterns.length > 0 ? (
            <Refreshing active={query.isFetching}>
              <div className="grid grid-cols-1 items-start gap-x-8 gap-y-5 lg:grid-cols-2">
                {byFamily(data.patterns).map((group) => (
                  <table key={group.family} className="w-full text-[13px]">
                    <caption className="mb-1 text-left text-xs font-medium text-text-2">{t(`family.${group.family}`)}</caption>
                    <thead className="sr-only">
                      <tr>
                        <th scope="col">{t("markets.patterns")}</th>
                        <th scope="col">{t("markets.bars")}</th>
                        <th scope="col">{t("markets.lastSeen")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.patterns.map((pattern) => (
                        <tr key={pattern.name} className="border-t hairline">
                          <th scope="row" className="py-0.5 pr-2 text-left font-normal">
                            <div className="flex min-w-0 items-center gap-1.5">
                              {pattern.state || pattern.count === 0 ? (
                                <span className="flex min-h-7 items-center gap-1.5 px-1.5 text-text-2">
                                  <DirectionMark direction={pattern.direction} />
                                  {label(pattern.name)}
                                </span>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  aria-pressed={shown === pattern.name}
                                  onClick={() => onShow(shown === pattern.name ? null : pattern.name)}
                                  className="h-auto min-h-7 justify-start px-1.5 text-left text-[13px] font-normal aria-pressed:bg-accent-wash aria-pressed:text-text"
                                >
                                  <DirectionMark direction={pattern.direction} />
                                  {label(pattern.name)}
                                </Button>
                              )}
                              {pattern.active ? <Badge tone="accent" icon={false}>{t("markets.now")}</Badge> : null}
                            </div>
                          </th>
                          <td className="tabular w-12 py-0.5 text-right text-text">{fmt.number(pattern.count, 0)}</td>
                          <td className="tabular w-28 py-0.5 pl-3 text-right whitespace-nowrap text-muted">
                            {pattern.last ? fmt.date(String(pattern.last)) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ))}
              </div>
            </Refreshing>
          ) : (
            <p className="text-text-2">{t("markets.noPattern")}</p>
          )}
          {data.events.length > 0 ? <p className="text-xs text-muted">{t("markets.patternsHint")}</p> : null}
          {latest.length > 0 ? (
            <div className="flex flex-col gap-1 border-t hairline pt-3">
              <p className="text-xs font-medium text-text-2">{t("markets.recent")}</p>
              <ul className="grid grid-cols-1 gap-x-6 gap-y-1 text-[13px] sm:grid-cols-2">
                {latest.map((event) => {
                  const pattern = data.patterns.find((p) => p.name === event.name);
                  return (
                    <li key={`${String(event.time)}-${event.name}`} className="flex min-w-0 items-center gap-2">
                      <span className="tabular w-24 shrink-0 text-muted">{fmt.date(String(event.time))}</span>
                      {pattern ? <DirectionMark direction={pattern.direction} /> : null}
                      <span className="truncate text-text">{label(event.name)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {data.unavailable.length > 0 ? (
            <div className="flex flex-col gap-1 border-t hairline pt-3">
              <p className="text-xs font-medium text-text-2">{t("markets.unavailable")}</p>
              {groupUnavailable(data.unavailable).map((group) => (
                <p key={group.missing.join()} className="text-xs text-muted">
                  {t("markets.needs")} {new Intl.ListFormat(locale, { type: "conjunction" }).format(group.missing.map((column) => t(`column.${column}`)))}:{" "}
                  {group.names.map(label).join(", ")}
                </p>
              ))}
            </div>
          ) : null}
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
