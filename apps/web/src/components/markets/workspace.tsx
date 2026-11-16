"use client";

/**
 * The chart workspace of an instrument: its prices with what the reader chooses to draw on
 * them (averages, bands, the structure's levels, Fibonacci) and under them (volume and the
 * oscillators of the catalogue), all on the same bars and read with one cursor.
 */

import { useCallback, useId, useMemo, useState, type ReactNode } from "react";

import { PriceChart, type IndicatorPane, type PriceBar, type PriceEvent, type PriceKind, type PriceLevel, type PriceOverlay, type PriceScale } from "@/components/charts/price";
import { useI18n, useTheme } from "@/components/providers";
import { Button, Card, Refreshing, Segmented, Skeleton } from "@/components/ui";
import type { useStructure, useTechnical } from "@/lib/api/queries";
import { spread } from "@/lib/util/chart";
import { availableCharts, availableOverlays, CHART_LINES, CHART_RANGE, indicatorLabel, OVERLAYS, pair, type Chart, type Overlay } from "@/lib/util/technical";

/** What can be drawn over the prices: indicator lines, the structure's levels, Fibonacci. */
type OverlayChoice = Overlay | "levels" | "fibonacci";

/** What can be stacked under the prices. */
type PaneChoice = "volume" | Chart;

/** The palette slot of each line of each overlay (fixed: a colour always means the same line). */
const OVERLAY_COLOURS: Record<Overlay, readonly number[]> = {
  averages: [1, 2],
  bollinger: [3, 3],
  keltner: [5, 5],
  ichimoku: [4, 6],
  sar: [0],
};

/** The palette slot of the second line of a pane (the MACD's signal). */
const SECOND_LINE = 6;

function Toggle({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Button size="sm" variant="ghost" aria-pressed={pressed} onClick={onClick} className="gap-1.5 border hairline aria-pressed:bg-accent-wash aria-pressed:text-text">
      {children}
    </Button>
  );
}

function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export function PriceWorkspace({
  symbol,
  subtitle,
  bars,
  fetching,
  zoomKey,
  technical,
  structure,
  events,
  digits,
  color,
  children,
}: {
  symbol: string;
  subtitle?: string;
  /** The bars to draw (``undefined`` while they load). */
  bars: PriceBar[] | undefined;
  fetching: boolean;
  /** What the bars are: while it holds, the reader's zoom is kept. */
  zoomKey: string;
  technical: ReturnType<typeof useTechnical>;
  structure: ReturnType<typeof useStructure>;
  events: readonly PriceEvent[];
  digits: number;
  color: string;
  children?: ReactNode;
}) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const overlaysLabel = useId();
  const panesLabel = useId();
  const [kind, setKind] = useState<PriceKind>("candles");
  const [scale, setScale] = useState<PriceScale>("linear");
  const [shownOverlays, setShownOverlays] = useState<ReadonlySet<OverlayChoice>>(() => new Set<OverlayChoice>(["averages"]));
  const [shownPanes, setShownPanes] = useState<ReadonlySet<PaneChoice>>(() => new Set<PaneChoice>(["volume", "RSI"]));
  const priceFormat = useMemo(() => (value: number) => fmt.number(value, digits), [fmt, digits]);
  const indicators = technical.data?.indicators;
  const ohlc = (bars?.length ?? 0) > 0 && (bars ?? []).every((bar) => bar.open != null && bar.high != null && bar.low != null);
  const hasVolume = (bars ?? []).some((bar) => (bar.volume ?? 0) > 0);

  const overlayChoices = useMemo<OverlayChoice[]>(() => {
    const lines = availableOverlays(indicators?.map((indicator) => indicator.name) ?? []);
    const levels: OverlayChoice[] = (structure.data?.levels.length ?? 0) > 0 ? ["levels"] : [];
    const fibonacci: OverlayChoice[] = (structure.data?.fibonacci?.levels.length ?? 0) > 0 ? ["fibonacci"] : [];
    return [...lines, ...levels, ...fibonacci];
  }, [indicators, structure.data]);
  const paneChoices = useMemo<PaneChoice[]>(
    () => [...(hasVolume ? (["volume"] as const) : []), ...availableCharts(indicators?.map((indicator) => indicator.name) ?? [])],
    [hasVolume, indicators],
  );
  const overlayColor = useCallback((overlay: Overlay, index: number) => tokens.series[OVERLAY_COLOURS[overlay][index] ?? 0] ?? tokens.text, [tokens]);

  const priceOverlays = useMemo<PriceOverlay[]>(() => {
    const byName = new Map(indicators?.map((indicator) => [indicator.name, indicator]) ?? []);
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
              values: new Map(indicator.values.map((point) => [String(point.time), point.value])),
            },
          ];
        }),
      );
  }, [indicators, shownOverlays, overlayColor]);

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
          // A support's name goes under its line and a resistance's over it: away from the prices between them.
          below: level.kind === "support",
        });
      }
    }
    if (shownOverlays.has("fibonacci")) {
      // Named at the left end of their lines, away from the levels' names at the right.
      for (const level of structure.data?.fibonacci?.levels ?? []) {
        found.push({ price: level.price, color: tokens.muted, label: fmt.percent(level.ratio, 1), side: "start" });
      }
    }
    return found;
  }, [structure.data, shownOverlays, tokens, t, fmt, digits]);

  const panes = useMemo<IndicatorPane[]>(() => {
    const byName = new Map(indicators?.map((indicator) => [indicator.name, indicator]) ?? []);
    const first = tokens.series[0] ?? tokens.text;
    const second = tokens.series[SECOND_LINE] ?? tokens.text2;
    return availableCharts([...byName.keys()])
      .filter((chart) => shownPanes.has(chart))
      .map((chart) => {
        const lines = CHART_LINES[chart].flatMap((name, index) => {
          const indicator = byName.get(name);
          if (!indicator) return [];
          return [
            {
              name: chart === "MACD" ? t(index === 0 ? "pane.macd.line" : "pane.macd.signal") : indicatorLabel(name, indicator.parameters),
              color: index === 0 ? first : second,
              values: new Map(indicator.values.map((point) => [String(point.time), point.value])),
            },
          ];
        });
        const head = byName.get(CHART_LINES[chart][0] ?? "");
        const [line, signal] = lines;
        return {
          id: chart,
          title: indicatorLabel(chart, head?.parameters ?? {}),
          lines,
          histogram: chart === "MACD" && line && signal ? { name: t("pane.macd.histogram"), values: spread(line.values, signal.values) } : undefined,
          zone: pair(head?.zone),
          range: CHART_RANGE[chart],
        };
      });
  }, [indicators, shownPanes, tokens, t]);

  const labels = useMemo(
    () => ({
      price: t("markets.price"),
      volume: t("markets.volume"),
      open: t("markets.open"),
      high: t("markets.high"),
      low: t("markets.low"),
      close: t("markets.close"),
      short: { open: t("markets.o"), high: t("markets.h"), low: t("markets.l"), close: t("markets.c") },
      change: t("markets.change"),
    }),
    [t],
  );

  return (
    <Card
      title={t("markets.price")}
      subtitle={subtitle}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {ohlc ? (
            <Segmented
              label={t("markets.chartKind")}
              value={kind}
              onChange={setKind}
              options={[
                { value: "candles", label: t("chartKind.candles") },
                { value: "line", label: t("chartKind.line") },
              ]}
            />
          ) : null}
          <Segmented
            label={t("markets.scale")}
            value={scale}
            onChange={setScale}
            options={[
              { value: "linear", label: t("scale.linear") },
              { value: "log", label: t("scale.log") },
            ]}
          />
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {overlayChoices.length > 0 || paneChoices.length > 0 ? (
          <div className="flex flex-col gap-2">
            {overlayChoices.length > 0 ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span id={overlaysLabel} className="w-24 shrink-0 text-xs text-muted">
                  {t("markets.overlays")}
                </span>
                <div role="group" aria-labelledby={overlaysLabel} className="flex min-w-0 flex-wrap items-center gap-1">
                  {overlayChoices.map((choice) => (
                    <Toggle key={choice} pressed={shownOverlays.has(choice)} onClick={() => setShownOverlays((shown) => toggled(shown, choice))}>
                      <span
                        aria-hidden="true"
                        className="inline-block h-0.5 w-3 rounded-full"
                        style={{
                          background: choice === "levels" ? `linear-gradient(90deg, ${tokens.up} 50%, ${tokens.down} 50%)` : choice === "fibonacci" ? tokens.muted : overlayColor(choice, 0),
                        }}
                      />
                      {t(`overlay.${choice}`)}
                    </Toggle>
                  ))}
                </div>
              </div>
            ) : null}
            {paneChoices.length > 0 ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span id={panesLabel} className="w-24 shrink-0 text-xs text-muted">
                  {t("markets.panes")}
                </span>
                <div role="group" aria-labelledby={panesLabel} className="flex min-w-0 flex-wrap items-center gap-1">
                  {paneChoices.map((choice) => (
                    <Toggle key={choice} pressed={shownPanes.has(choice)} onClick={() => setShownPanes((shown) => toggled(shown, choice))}>
                      {choice === "volume" ? t("pane.volume") : choice}
                    </Toggle>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
        {bars ? (
          <Refreshing active={fetching}>
            <PriceChart
              bars={bars}
              format={priceFormat}
              color={color}
              label={`${t("markets.price")} ${symbol}`}
              labels={labels}
              kind={kind}
              scale={scale}
              volume={shownPanes.has("volume")}
              events={events}
              overlays={priceOverlays}
              levels={priceLevels}
              panes={panes}
              zoomKey={zoomKey}
            />
          </Refreshing>
        ) : (
          <Skeleton className="h-[520px]" />
        )}
        <p className="text-xs text-muted">{t("markets.zoomHint")}</p>
        {children}
      </div>
    </Card>
  );
}
