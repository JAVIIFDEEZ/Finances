"use client";

/**
 * The technical analysis of an instrument (ADR-0034, ADR-0037): a summary of trend, momentum,
 * volatility and volume; the oscillators with their conventional zones; and every indicator by
 * family with how it reads on the last bar.
 */

import { useMemo, useState, type ReactNode } from "react";

import { TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Card, ProblemAlert, Refreshing, Segmented, Skeleton } from "@/components/ui";
import type { useTechnical } from "@/lib/api/queries";
import { fill, isMessageKey } from "@/lib/i18n/messages";
import {
  availableCharts,
  byIndicatorFamily,
  CHART_LINES,
  groupUnavailable,
  indicatorLabel,
  pair,
  readingKey,
  readingSide,
  type Chart,
} from "@/lib/util/technical";

type TechnicalQuery = ReturnType<typeof useTechnical>;
type Indicator = NonNullable<TechnicalQuery["data"]>["indicators"][number];

/** An indicator's name in the interface language (its catalogue name if the web does not know it). */
export function useIndicatorName(): (name: string) => string {
  const { t } = useI18n();
  return useMemo(
    () => (name: string) => {
      const key = `indicator.${name}`;
      return isMessageKey(key) ? t(key) : name;
    },
    [t],
  );
}

/** The mark of a reading: a triangle up or down, a dot when it points nowhere; colour and shape together. */
export function SideMark({ side }: { side: "up" | "down" | "flat" }) {
  const { tokens } = useTheme();
  const color = side === "up" ? tokens.up : side === "down" ? tokens.down : tokens.muted;
  return (
    <span aria-hidden="true" className="inline-block w-3 shrink-0 text-center text-[10px]" style={{ color }}>
      {side === "up" ? "▲" : side === "down" ? "▼" : "●"}
    </span>
  );
}

/** How an indicator reads, in words, with its mark. */
function ReadingChip({ indicator }: { indicator: Indicator }) {
  const { t } = useI18n();
  if (!indicator.reading) return <span className="text-muted">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-text-2">
      <SideMark side={readingSide(indicator.name, indicator.reading)} />
      {t(readingKey(indicator.name, indicator.reading))}
    </span>
  );
}

/** An indicator's value in its own units: percent, times, or price digits for the levels. */
function useValueFormat(digits: number): (indicator: Indicator) => string {
  const { fmt } = useI18n();
  return useMemo(
    () => (indicator: Indicator) => {
      const value = indicator.latest;
      if (indicator.name === "ATR_PCT") return fmt.percent(value == null ? value : value / 100, 2);
      if (indicator.name === "VOLRATIO") return value == null ? "—" : `${fmt.number(value, 2)}×`;
      if (indicator.name === "CMF") return fmt.number(value, 3);
      if (indicator.kind === "level") return fmt.number(value, digits);
      return fmt.number(value, 2);
    },
    [fmt, digits],
  );
}

function Tile({ label, value, detail, side, children }: { label: string; value: string; detail?: string; side?: "up" | "down" | "flat"; children?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border hairline bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-[0.04em] text-text-2">{label}</p>
      <p className="flex items-baseline gap-2 text-lg font-semibold tracking-tight text-text">
        {side ? <SideMark side={side} /> : null}
        <span className="tabular truncate">{value}</span>
      </p>
      {detail ? <p className="text-xs text-muted">{detail}</p> : null}
      {children}
    </div>
  );
}

/** Trend, momentum, volatility and volume on the last bar, each from the indicator that reads it best. */
export function TechnicalSummary({ query }: { query: TechnicalQuery }) {
  const { t, fmt } = useI18n();
  const data = query.data;
  if (!data) return query.isLoading ? <Skeleton className="h-[104px]" /> : null;
  const by = new Map(data.indicators.map((i) => [i.name, i]));
  const sma = by.get("SMA");
  const adx = by.get("ADX");
  const rsi = by.get("RSI");
  const atr = by.get("ATR_PCT");
  const volume = by.get("VOLRATIO");
  const word = (indicator: Indicator | undefined) => (indicator?.reading ? t(readingKey(indicator.name, indicator.reading)) : "—");
  const percentileText = (indicator: Indicator | undefined) =>
    indicator?.percentile == null ? undefined : fill(t("markets.percentileOf"), { p: fmt.number(indicator.percentile * 100, 0) });
  const window = (indicator: Indicator | undefined) => indicator?.parameters.window ?? "";
  return (
    <section aria-label={t("markets.summary")} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.04em] text-text-2">{t("markets.summary")}</h2>
        <p className="text-xs text-muted">{t("markets.summaryNote")}</p>
      </div>
      <Refreshing active={query.isFetching}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Tile
            label={t("markets.trend")}
            value={sma?.reading ? fill(t(sma.reading === "above" ? "markets.aboveAverage" : "markets.belowAverage"), { n: window(sma) }) : "—"}
            side={sma?.reading ? readingSide("SMA", sma.reading) : undefined}
            detail={adx ? `ADX ${fmt.number(adx.latest, 1)} · ${word(adx)}` : undefined}
          />
          <Tile
            label={t("markets.momentum")}
            value={rsi ? `RSI ${fmt.number(rsi.latest, 1)}` : "—"}
            side={rsi?.reading ? readingSide("RSI", rsi.reading) : undefined}
            detail={rsi?.zone ? `${word(rsi)} · ${t("markets.zone")} ${fmt.number(rsi.zone[0], 0)}–${fmt.number(rsi.zone[1], 0)}` : word(rsi)}
          />
          <Tile
            label={t("markets.volatility")}
            value={atr ? `ATR ${fmt.percent(atr.latest == null ? null : atr.latest / 100, 2)}` : "—"}
            detail={atr ? [word(atr), percentileText(atr)].filter(Boolean).join(" · ") : undefined}
          />
          <Tile
            label={t("markets.volumeTile")}
            value={volume?.latest != null ? fill(t("markets.timesAverage"), { x: fmt.number(volume.latest, 2), n: window(volume) }) : "—"}
            detail={volume ? [word(volume), percentileText(volume)].filter(Boolean).join(" · ") : t("markets.noVolume")}
          />
        </div>
      </Refreshing>
    </section>
  );
}

/** The oscillators with their conventional zones, and every indicator by family with its reading. */
export function TechnicalCard({ query, digits }: { query: TechnicalQuery; digits: number }) {
  const { t, fmt, locale } = useI18n();
  const { tokens } = useTheme();
  const name = useIndicatorName();
  const format = useValueFormat(digits);
  const data = query.data;
  const charts = availableCharts(data?.indicators.map((indicator) => indicator.name) ?? []);
  const [picked, setPicked] = useState<Chart>("RSI");
  const chart = charts.includes(picked) ? picked : charts[0];
  const byName = new Map(data?.indicators.map((indicator) => [indicator.name, indicator]) ?? []);
  const two = useMemo(() => (v: number) => fmt.number(v, 2), [fmt]);
  const head = chart ? byName.get(CHART_LINES[chart][0] ?? "") : undefined;
  return (
    <Card title={t("markets.technical")} subtitle={t("markets.technicalNote")}>
      {query.isLoading ? (
        <Skeleton className="h-[420px]" />
      ) : query.isError ? (
        <ProblemAlert error={query.error} onRetry={() => void query.refetch()} />
      ) : data ? (
        <div className="flex flex-col gap-6">
          {chart && head ? (
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Segmented label={t("markets.indicator")} value={chart} options={charts.map((value) => ({ value, label: value }))} onChange={setPicked} />
                <p className="flex items-center gap-2 text-[13px] text-text-2">
                  <span>
                    {name(head.name)} <span className="font-mono text-xs text-muted">{indicatorLabel(head.name, head.parameters)}</span>
                  </span>
                  <strong className="tabular font-semibold text-text">{format(head)}</strong>
                  <ReadingChip indicator={head} />
                </p>
              </div>
              <Refreshing active={query.isFetching}>
                <TimeSeriesChart
                  height={260}
                  label={chart}
                  format={two}
                  zone={pair(head.zone)}
                  reference={head.zone ? undefined : 0}
                  lines={CHART_LINES[chart].map((line, index) => ({
                    name: indicatorLabel(line, byName.get(line)?.parameters ?? {}),
                    color: tokens.series[index] ?? tokens.text,
                    points: (byName.get(line)?.values ?? []).map((p) => ({ time: String(p.time), value: p.value })),
                  }))}
                />
              </Refreshing>
            </div>
          ) : null}
          <div className="grid grid-cols-1 items-start gap-x-8 gap-y-6 border-t hairline pt-5 lg:grid-cols-2">
            {byIndicatorFamily(data.indicators).map((group) => (
              <table key={group.family} className="w-full text-[13px]">
                <caption className="mb-1 text-left text-xs font-medium text-text-2">{t(`family.${group.family}`)}</caption>
                <thead className="sr-only">
                  <tr>
                    <th scope="col">{t("markets.indicator")}</th>
                    <th scope="col">{t("markets.value")}</th>
                    <th scope="col">{t("markets.reading")}</th>
                  </tr>
                </thead>
                <tbody>
                  {group.indicators.map((indicator) => (
                    <tr key={indicator.name} className="border-t hairline">
                      <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                        <span className="block text-text">{name(indicator.name)}</span>
                        <span className="block font-mono text-[11px] text-muted">{indicatorLabel(indicator.name, indicator.parameters)}</span>
                        {/* On a phone the reading goes under the name: a third column would squeeze it. */}
                        <span className="mt-0.5 block text-xs sm:hidden">
                          <ReadingChip indicator={indicator} />
                        </span>
                      </th>
                      <td className="tabular w-24 py-1.5 align-top text-right text-text sm:align-middle">{format(indicator)}</td>
                      <td className="hidden w-40 py-1.5 pl-4 text-left text-xs sm:table-cell">
                        <ReadingChip indicator={indicator} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
          {data.unavailable.length > 0 ? (
            <div className="flex flex-col gap-1 border-t hairline pt-3">
              <p className="text-xs font-medium text-text-2">{t("markets.unavailable")}</p>
              {groupUnavailable(data.unavailable).map((group) => (
                <p key={group.missing.join()} className="text-xs text-muted">
                  {t("markets.needs")} {new Intl.ListFormat(locale, { type: "conjunction" }).format(group.missing.map((column) => t(`column.${column}`)))}:{" "}
                  {group.names.join(", ")}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
