"use client";

/**
 * The price chart of an instrument, as a trading desk reads it: candles (or the close) on a
 * price axis at the right, where the last bar is; volume and oscillators stacked under it on
 * the same bars; one crosshair across all panes; a readout of the bar under the cursor instead
 * of a box over the prices; and a zoom that survives adding a line.
 *
 * The time axis has one slot per bar: a closed market leaves no gap, because nothing traded
 * there. The scale can be logarithmic, where equal distances are equal percentage moves.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EChart, zoomWindow, type ChartInstance, type ChartOption } from "@/components/charts/echart";
import { base, FONT, type Format } from "@/components/charts/parts";
import { useI18n, useTheme } from "@/components/providers";
import { barChange, extent, linearTicks, logTicks, paneLayout, spacedTicks, tickKind, tickUnit, unitStart, type TickUnit } from "@/lib/util/chart";

export interface PriceBar {
  time: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
}

/** A line drawn over the prices (an average, a band): one value per bar time, gaps as null. */
export interface PriceOverlay {
  name: string;
  color: string;
  values: ReadonlyMap<string, number | null>;
  /** ``dashed`` for bands and channels; ``dots`` for a stop such as the parabolic SAR. */
  style?: "solid" | "dashed" | "dots";
}

/** A horizontal level over the prices (a support, a resistance, a Fibonacci ratio). */
export interface PriceLevel {
  price: number;
  /** Written on the line; empty to draw the line alone (labels must not overlap). */
  label: string;
  color: string;
  /** The end of the line its label sits at (``end`` by default, next to the price axis). */
  side?: "start" | "end";
  /** Whether the label goes under the line (a support: the prices are above it). */
  below?: boolean;
}

/** An event on a bar (a price pattern): drawn as a marker on it and named in the readout. */
export interface PriceEvent {
  time: string;
  label: string;
  direction: "bullish" | "bearish" | "neutral";
}

/** An oscillator in its own pane under the prices, on the same bars. */
export interface IndicatorPane {
  id: string;
  /** What the pane is, with its parameters: ``RSI (14)``. */
  title: string;
  lines: readonly { name: string; color: string; values: ReadonlyMap<string, number | null> }[];
  /** Bars around zero behind the lines (the MACD histogram). */
  histogram?: { name: string; values: ReadonlyMap<string, number | null> };
  /** The conventional zone: shaded, with its bounds drawn and labelled. */
  zone?: readonly [number, number] | null;
  /** A fixed scale (0–100 for the bounded oscillators); otherwise the data decide. */
  range?: readonly [number, number];
  digits?: number;
}

export type PriceKind = "candles" | "line";
export type PriceScale = "linear" | "log";

export interface PriceLabels {
  price: string;
  volume: string;
  open: string;
  high: string;
  low: string;
  close: string;
  /** One or two letters for the readout: O, H, L, C. */
  short: { open: string; high: string; low: string; close: string };
  change: string;
}

const PRICE_HEIGHT = 340;
const VOLUME_HEIGHT = 64;
const PANE_HEIGHT = 104;
const AXIS_HEIGHT = 22;
const SLIDER_HEIGHT = 20;
const LEFT = 8;
/** Room a mark of the time axis needs, in pixels: what decides how fine the marks can be. */
const LABEL_WIDTH = 48;

const NO_EVENTS: readonly PriceEvent[] = [];
const NO_OVERLAYS: readonly PriceOverlay[] = [];
const NO_LEVELS: readonly PriceLevel[] = [];
const NO_PANES: readonly IndicatorPane[] = [];

/** What the listeners of the chart need of the last render (they outlive it). */
interface Live {
  times: readonly string[];
  lows: readonly number[];
  highs: readonly number[];
  log: boolean;
  right: number;
  view: { unit: TickUnit };
  timeAxes: () => unknown[];
  logKey: string;
}

export function PriceChart({
  bars,
  format,
  label,
  color,
  labels,
  kind = "candles",
  scale = "linear",
  volume: wantVolume = true,
  events = NO_EVENTS,
  overlays = NO_OVERLAYS,
  levels = NO_LEVELS,
  panes = NO_PANES,
  zoomKey,
}: {
  bars: PriceBar[];
  format: Format;
  label: string;
  color: string;
  labels: PriceLabels;
  kind?: PriceKind;
  scale?: PriceScale;
  /** Whether the volume pane is wanted (it is only drawn if the bars carry volume). */
  volume?: boolean;
  events?: readonly PriceEvent[];
  overlays?: readonly PriceOverlay[];
  levels?: readonly PriceLevel[];
  panes?: readonly IndicatorPane[];
  /** What the bars are (instrument, frequency, range): while it holds, the zoom is kept. */
  zoomKey?: string;
}) {
  const { tokens } = useTheme();
  const { fmt } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const instance = useRef<ChartInstance | null>(null);
  const live = useRef<Live | null>(null);

  const ohlc = bars.length > 0 && bars.every((b) => b.open != null && b.high != null && b.low != null);
  const candles = ohlc && kind === "candles";
  const hasVolume = bars.some((b) => (b.volume ?? 0) > 0);
  const showVolume = wantVolume && hasVolume;
  const log = scale === "log";

  const layout = useMemo(
    () =>
      paneLayout(
        [
          { id: "price", height: PRICE_HEIGHT },
          ...(showVolume ? [{ id: "volume", height: VOLUME_HEIGHT }] : []),
          ...panes.map((pane) => ({ id: pane.id, height: PANE_HEIGHT })),
        ],
        { top: 6, gap: 12, foot: AXIS_HEIGHT + SLIDER_HEIGHT + 14 },
      ),
    [showVolume, panes],
  );

  const built = useMemo(() => {
    const times = bars.map((b) => b.time);
    const closes = bars.map((b) => b.close);
    const lows = bars.map((b) => (ohlc ? (b.low ?? b.close) : b.close));
    const highs = bars.map((b) => (ohlc ? (b.high ?? b.close) : b.close));
    const y = (value: number | null | undefined): number | null => (value == null ? null : log ? (value > 0 ? Math.log10(value) : null) : value);
    const price = (value: number) => (log ? 10 ** value : value);
    const last = bars[bars.length - 1];
    const range = extent([...lows, ...highs]);
    // The price axis is as wide as its longest figure needs, and every pane shares that width:
    // the bars of all panes stay one above the other.
    const widest = Math.max(...(range ? range.map((v) => format(v).length) : [4]), fmt.compact(Math.max(0, ...bars.map((b) => b.volume ?? 0))).length);
    const right = Math.min(104, Math.max(52, Math.round(widest * 6.4) + 18));
    const view = { unit: tickUnit(times, 0, times.length - 1, 14) };
    const isTick = (index: number) => index > 0 && unitStart(times[index - 1] ?? "", times[index] ?? "", view.unit);
    const position = new Map(times.map((time, i) => [time, i]));
    // The axis numbers its marks, not the bars: the bar of a mark is found by its time.
    const tickText = (value: string) => {
      const index = position.get(value) ?? 0;
      const what = index > 0 ? tickKind(times[index - 1] ?? "", value, view.unit) : "day";
      return what === "year" ? `{year|${fmt.year(value)}}` : what === "month" ? fmt.month(value) : fmt.day(value);
    };
    const tag = { backgroundColor: tokens.text, color: tokens.surface, fontSize: 11, fontFamily: FONT, padding: [3, 5], borderRadius: 2, margin: 4 };
    const pointerLine = { color: tokens.muted, width: 1, type: "dashed" };

    const count = layout.panes.length;
    const grid = layout.panes.map((pane) => ({ left: LEFT, right, top: pane.top, height: pane.height, outerBoundsMode: "none" }));
    const timeAxis = (gridIndex: number) => {
      const bottom = gridIndex === count - 1;
      return {
        type: "category",
        gridIndex,
        data: times,
        boundaryGap: true,
        axisLine: { lineStyle: { color: bottom ? tokens.axis : tokens.grid } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: bottom
          ? {
              show: true,
              color: tokens.muted,
              fontSize: 11,
              hideOverlap: true,
              interval: (index: number) => isTick(index),
              formatter: tickText,
              rich: { year: { color: tokens.text2, fontWeight: 600, fontSize: 11, fontFamily: FONT } },
            }
          : { show: false },
        axisPointer: { show: true, type: "line", lineStyle: pointerLine, label: { show: bottom, ...tag, formatter: (p: { value: string }) => fmt.date(p.value) } },
      };
    };
    const valueAxis = (gridIndex: number, extra: Record<string, unknown>) => ({
      type: "value",
      gridIndex,
      position: "right",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: tokens.grid, width: 1 } },
      axisPointer: { show: false },
      ...extra,
    });
    const axisText = { color: tokens.muted, fontSize: 11, margin: 8 };

    // ── Prices ──
    const onBar = new Map<string, PriceEvent[]>();
    for (const event of events) onBar.set(event.time, [...(onBar.get(event.time) ?? []), event]);
    const markerColor = (event: PriceEvent) => (event.direction === "bullish" ? tokens.up : event.direction === "bearish" ? tokens.down : tokens.muted);
    const markers = events.flatMap((event) => {
      const bar = bars[position.get(event.time) ?? -1];
      if (!bar) return [];
      const up = event.direction === "bullish";
      const down = event.direction === "bearish";
      return [
        {
          coord: [event.time, y(up ? (bar.low ?? bar.close) : down ? (bar.high ?? bar.close) : bar.close)],
          symbol: up || down ? "triangle" : "diamond",
          symbolSize: 10,
          symbolRotate: down ? 180 : 0,
          symbolOffset: [0, up ? 10 : down ? -10 : 0],
          itemStyle: { color: markerColor(event), borderColor: tokens.surface, borderWidth: 1 },
        },
      ];
    });
    const lines: unknown[] = levels.map((level) => ({
      yAxis: y(level.price),
      lineStyle: { color: level.color, width: 1, type: "dashed" },
      label: {
        show: level.label !== "",
        position: `inside${level.side === "start" ? "Start" : "End"}${level.below ? "Bottom" : "Top"}`,
        formatter: level.label,
        color: tokens.text2,
        fontSize: 10,
        distance: [4, 2],
        textBorderColor: tokens.surface,
        textBorderWidth: 2,
      },
    }));
    if (last) {
      // Where the price is now: a line across the pane and its figure on the axis.
      lines.push({
        yAxis: y(last.close),
        lineStyle: { color: tokens.muted, width: 1, type: "dotted" },
        label: { show: true, position: "end", distance: 4, formatter: format(last.close), backgroundColor: tokens.axis, color: tokens.text, fontSize: 11, fontFamily: FONT, padding: [3, 5], borderRadius: 2 },
      });
    }
    const marks = {
      markPoint: markers.length > 0 ? { silent: true, animation: false, label: { show: false }, data: markers } : undefined,
      markLine: lines.length > 0 ? { silent: true, symbol: "none", animation: false, data: lines } : undefined,
    };
    const series: unknown[] = [
      candles
        ? {
            name: labels.price,
            type: "candlestick",
            xAxisIndex: 0,
            yAxisIndex: 0,
            barMaxWidth: 14,
            itemStyle: { color: tokens.surface, color0: tokens.down, borderColor: tokens.up, borderColor0: tokens.down, borderWidth: 1 },
            emphasis: { disabled: true },
            ...marks,
            data: bars.map((b) => [y(b.open), y(b.close), y(b.low), y(b.high)]),
          }
        : {
            name: labels.price,
            type: "line",
            xAxisIndex: 0,
            yAxisIndex: 0,
            showSymbol: false,
            lineStyle: { width: 2, color, join: "round" },
            itemStyle: { color },
            emphasis: { disabled: true },
            ...marks,
            data: closes.map((close) => y(close)),
          },
      ...overlays.map((overlay) =>
        overlay.style === "dots"
          ? {
              name: overlay.name,
              type: "scatter",
              xAxisIndex: 0,
              yAxisIndex: 0,
              symbolSize: 3,
              silent: true,
              itemStyle: { color: overlay.color },
              data: bars.map((b) => y(overlay.values.get(b.time))),
            }
          : {
              name: overlay.name,
              type: "line",
              xAxisIndex: 0,
              yAxisIndex: 0,
              showSymbol: false,
              connectNulls: false,
              silent: true,
              lineStyle: { width: 1.5, color: overlay.color, type: overlay.style === "dashed" ? "dashed" : "solid" },
              itemStyle: { color: overlay.color },
              emphasis: { disabled: true },
              data: bars.map((b) => y(overlay.values.get(b.time))),
            },
      ),
    ];
    const visibleLog = range ? logTicks(range[0], range[1], 6).map((tick) => Math.log10(tick)) : [];
    const yAxis: unknown[] = [
      valueAxis(0, {
        scale: true,
        splitNumber: 5,
        // A log scale has its own marks: the axis only needs a little air around the data.
        ...(log ? { min: (v: { min: number; max: number }) => v.min - (v.max - v.min) * 0.04, max: (v: { min: number; max: number }) => v.max + (v.max - v.min) * 0.04 } : {}),
        axisLabel: { ...axisText, formatter: (value: number) => format(price(value)), ...(log ? { customValues: visibleLog } : {}) },
        ...(log ? { axisTick: { show: false, customValues: visibleLog } } : {}),
        axisPointer: { show: true, lineStyle: pointerLine, label: { show: true, ...tag, formatter: (p: { value: number }) => format(price(p.value)) } },
      }),
    ];
    const xAxis: unknown[] = [timeAxis(0)];

    // ── Volume ──
    if (showVolume) {
      const index = xAxis.length;
      xAxis.push(timeAxis(index));
      yAxis.push(
        valueAxis(index, {
          min: 0,
          splitNumber: 2,
          splitLine: { show: false },
          // The top figure would touch the lowest price above it: the middle one says the scale.
          axisLabel: { ...axisText, showMinLabel: false, showMaxLabel: false, formatter: (value: number) => fmt.compact(value) },
        }),
      );
      series.push({
        name: labels.volume,
        type: "bar",
        xAxisIndex: index,
        yAxisIndex: index,
        barMaxWidth: 14,
        barCategoryGap: "20%",
        silent: true,
        // Toned by the bar's direction, as the candle above it says in shape too.
        data: bars.map((b, i) => {
          const from = ohlc ? (b.open ?? b.close) : (closes[i - 1] ?? b.close);
          return { value: b.volume ?? null, itemStyle: { color: b.close >= from ? tokens.up : tokens.down, opacity: 0.5, borderRadius: [1, 1, 0, 0] } };
        }),
      });
    }

    // ── Oscillators ──
    for (const pane of panes) {
      const index = xAxis.length;
      xAxis.push(timeAxis(index));
      const digits = pane.digits ?? 2;
      const values = [...pane.lines.flatMap((line) => [...line.values.values()]), ...(pane.histogram ? [...pane.histogram.values.values()] : [])];
      const found = extent([...values, ...(pane.zone ?? []), ...(pane.histogram ? [0] : [])]) ?? [0, 1];
      const pad = (found[1] - found[0] || 1) * 0.08;
      const [min, max] = pane.range ?? [found[0] - pad, found[1] + pad];
      const centred = !pane.zone && min < 0 && max > 0;
      const ticks = pane.zone ? spacedTicks(pane.zone, max - min, PANE_HEIGHT) : centred ? [0] : linearTicks(min, max, 2);
      yAxis.push(
        valueAxis(index, {
          min,
          max,
          splitLine: { show: !pane.zone && !centred, lineStyle: { color: tokens.grid, width: 1 } },
          axisTick: { show: false, customValues: ticks },
          axisLabel: { ...axisText, customValues: ticks, formatter: (value: number) => fmt.number(value, Number.isInteger(value) ? 0 : digits) },
        }),
      );
      if (pane.histogram) {
        const histogram = pane.histogram;
        series.push({
          name: histogram.name,
          type: "bar",
          xAxisIndex: index,
          yAxisIndex: index,
          barMaxWidth: 14,
          barCategoryGap: "20%",
          silent: true,
          data: bars.map((b) => {
            const value = histogram.values.get(b.time) ?? null;
            return { value, itemStyle: { color: (value ?? 0) >= 0 ? tokens.up : tokens.down, opacity: 0.45 } };
          }),
        });
      }
      pane.lines.forEach((line, order) => {
        const bounds = pane.zone ? pane.zone.map((bound) => ({ yAxis: bound })) : centred ? [{ yAxis: 0 }] : [];
        series.push({
          name: line.name,
          type: "line",
          xAxisIndex: index,
          yAxisIndex: index,
          showSymbol: false,
          connectNulls: false,
          silent: true,
          lineStyle: { width: 1.5, color: line.color, join: "round" },
          itemStyle: { color: line.color },
          emphasis: { disabled: true },
          markLine:
            order === 0 && bounds.length > 0
              ? { silent: true, symbol: "none", animation: false, label: { show: false }, lineStyle: { color: tokens.axis, width: 1, type: pane.zone ? "dashed" : "solid" }, data: bounds }
              : undefined,
          markArea: order === 0 && pane.zone ? { silent: true, itemStyle: { color: tokens.muted, opacity: 0.08 }, data: [[{ yAxis: pane.zone[0] }, { yAxis: pane.zone[1] }]] } : undefined,
          data: bars.map((b) => line.values.get(b.time) ?? null),
        });
      });
    }

    const axes = xAxis.map((_, i) => i);
    const option: ChartOption = {
      ...base(tokens),
      animation: false,
      grid,
      axisPointer: { link: [{ xAxisIndex: "all" }], triggerOn: "mousemove|click" },
      xAxis,
      yAxis,
      dataZoom: [
        { type: "inside", xAxisIndex: axes, zoomOnMouseWheel: "ctrl", moveOnMouseMove: true, moveOnMouseWheel: false, preventDefaultMouseMove: false },
        {
          type: "slider",
          xAxisIndex: axes,
          left: LEFT,
          right,
          top: layout.height - SLIDER_HEIGHT - 4,
          height: SLIDER_HEIGHT,
          borderColor: tokens.grid,
          backgroundColor: "transparent",
          fillerColor: `${tokens.muted}26`,
          dataBackground: { lineStyle: { color: tokens.axis, width: 1 }, areaStyle: { color: tokens.axis, opacity: 0.35 } },
          selectedDataBackground: { lineStyle: { color: tokens.muted, width: 1 }, areaStyle: { color: tokens.muted, opacity: 0.25 } },
          handleSize: "110%",
          handleStyle: { color: tokens.surface, borderColor: tokens.muted, borderWidth: 1 },
          moveHandleSize: 0,
          showDetail: false,
          brushSelect: false,
          emphasis: { handleStyle: { borderColor: tokens.text2 } },
        },
      ],
      series,
    };
    const timeAxes = () => xAxis.map((_, i) => (i === count - 1 ? { axisLabel: { interval: (index: number) => isTick(index) } } : {}));
    const state: Live = { times, lows, highs, log, right, view, timeAxes, logKey: visibleLog.join() };
    return { option, state, closes, onBar, markerColor, right };
  }, [bars, ohlc, candles, showVolume, log, format, labels, color, tokens, fmt, events, overlays, levels, panes, layout]);

  /** Fit the marks of the axes to what is in view: the time unit, and the ticks of a log scale. */
  const sync = useCallback(() => {
    const chart = instance.current;
    const state = live.current;
    if (!chart || !state || chart.isDisposed()) return;
    const zoom = zoomWindow(chart) ?? { start: 0, end: 100 };
    const lastIndex = state.times.length - 1;
    const from = Math.round((zoom.start / 100) * lastIndex);
    const to = Math.round((zoom.end / 100) * lastIndex);
    const patch: Record<string, unknown> = {};
    const unit = tickUnit(state.times, from, to, Math.max(2, Math.floor((chart.getWidth() - LEFT - state.right) / LABEL_WIDTH)));
    if (unit !== state.view.unit) {
      state.view.unit = unit;
      patch.xAxis = state.timeAxes();
    }
    if (state.log) {
      const range = extent([...state.lows.slice(from, to + 1), ...state.highs.slice(from, to + 1)]);
      const ticks = range ? logTicks(range[0], range[1], 6).map((tick) => Math.log10(tick)) : [];
      if (ticks.join() !== state.logKey) {
        state.logKey = ticks.join();
        patch.yAxis = [{ axisLabel: { customValues: ticks }, axisTick: { customValues: ticks } }];
      }
    }
    if (Object.keys(patch).length > 0) chart.setOption(patch);
  }, []);

  const onReady = useCallback(
    (chart: ChartInstance) => {
      instance.current = chart;
      let frame = requestAnimationFrame(sync);
      // The chart is still drawing when it reports a zoom: fit the axes on the next frame.
      const later = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(sync);
      };
      chart.on("datazoom", later);
      chart.on("updateAxisPointer", (event) => {
        const axes = (event as { axesInfo?: { axisDim: string; value: number }[] }).axesInfo ?? [];
        const x = axes.find((axis) => axis.axisDim === "x");
        setHover(x ? Number(x.value) : null);
      });
      chart.getZr().on("globalout", () => setHover(null));
      const observer = new ResizeObserver(later);
      observer.observe(chart.getDom());
      return () => {
        cancelAnimationFrame(frame);
        observer.disconnect();
        instance.current = null;
      };
    },
    [sync],
  );

  // A new option starts from the whole range: fit its axes to the zoom the chart kept.
  useEffect(() => {
    live.current = built.state;
    const frame = requestAnimationFrame(sync);
    return () => cancelAnimationFrame(frame);
  }, [built, sync]);

  const shown = hover !== null && hover >= 0 && hover < bars.length ? hover : bars.length - 1;
  const bar = bars[shown];
  const change = barChange(built.closes, shown);
  const figure = "tabular font-medium text-text";
  const paneValue = (pane: IndicatorPane, values: ReadonlyMap<string, number | null>) => fmt.number(bar ? (values.get(bar.time) ?? null) : null, pane.digits ?? 2);

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {bar ? (
        <div className="flex min-h-5 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-2" data-testid="price-readout">
          <span className="tabular text-muted">{fmt.date(bar.time)}</span>
          {ohlc ? (
            <>
              <span>
                <abbr title={labels.open} className="no-underline">
                  {labels.short.open}
                </abbr>{" "}
                <span className={figure}>{format(bar.open ?? Number.NaN)}</span>
              </span>
              <span>
                <abbr title={labels.high} className="no-underline">
                  {labels.short.high}
                </abbr>{" "}
                <span className={figure}>{format(bar.high ?? Number.NaN)}</span>
              </span>
              <span>
                <abbr title={labels.low} className="no-underline">
                  {labels.short.low}
                </abbr>{" "}
                <span className={figure}>{format(bar.low ?? Number.NaN)}</span>
              </span>
            </>
          ) : null}
          <span>
            <abbr title={labels.close} className="no-underline">
              {labels.short.close}
            </abbr>{" "}
            <span className={figure}>{format(bar.close)}</span>
          </span>
          {change ? (
            <span className="inline-flex items-center gap-1" title={labels.change}>
              <span aria-hidden="true" className="text-[10px]" style={{ color: change.relative > 0 ? tokens.up : change.relative < 0 ? tokens.down : tokens.muted }}>
                {change.relative > 0 ? "▲" : change.relative < 0 ? "▼" : "●"}
              </span>
              <span className={figure}>{fmt.signedPercent(change.relative, 2)}</span>
            </span>
          ) : null}
          {overlays.map((overlay) => (
            <span key={overlay.name} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-0.5 w-3 rounded-full" style={{ background: overlay.color }} />
              {overlay.name} <span className={figure}>{format(overlay.values.get(bar.time) ?? Number.NaN)}</span>
            </span>
          ))}
          {(built.onBar.get(bar.time) ?? []).map((event) => (
            <span key={event.label} className="inline-flex items-center gap-1 text-text">
              <span aria-hidden="true" className="text-[10px]" style={{ color: built.markerColor(event) }}>
                {event.direction === "bullish" ? "▲" : event.direction === "bearish" ? "▼" : "◆"}
              </span>
              {event.label}
            </span>
          ))}
        </div>
      ) : null}
      <div className="relative">
        <EChart option={built.option} height={layout.height} label={label} onReady={onReady} zoomKey={zoomKey} />
        {/* What each pane under the prices is, with its figures on the bar being read. */}
        {bar
          ? layout.panes.slice(1).map((slot) => {
              const pane = panes.find((candidate) => candidate.id === slot.id);
              return (
                <p
                  key={slot.id}
                  className="pointer-events-none absolute flex max-w-[calc(100%-7rem)] flex-wrap items-center gap-x-2.5 rounded-sm bg-surface/80 px-1 text-[11px] leading-4 text-text-2"
                  style={{ top: slot.top + 1, left: LEFT }}
                >
                  {pane ? (
                    <>
                      <span className="font-medium">{pane.title}</span>
                      {pane.lines.map((line) => (
                        <span key={line.name} className="inline-flex items-center gap-1">
                          <span aria-hidden="true" className="inline-block h-0.5 w-2.5 rounded-full" style={{ background: line.color }} />
                          {pane.lines.length > 1 ? line.name : null}
                          <span className={figure}>{paneValue(pane, line.values)}</span>
                        </span>
                      ))}
                      {pane.histogram ? (
                        <span>
                          {pane.histogram.name} <span className={figure}>{paneValue(pane, pane.histogram.values)}</span>
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <span className="font-medium">{labels.volume}</span>
                      <span className={figure}>{fmt.compact(bar.volume ?? null)}</span>
                    </>
                  )}
                </p>
              );
            })
          : null}
      </div>
    </div>
  );
}
