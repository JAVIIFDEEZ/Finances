"use client";

/**
 * The platform's charts, built on {@link EChart} with the data-viz rules: 2px lines, ~10%
 * area washes, solid hairline grids, a crosshair tooltip listing every series (values lead,
 * names follow, keyed by a short stroke), a legend from two series up with selective end
 * labels, the 2px surface gap between bars, a 2px surface ring on dots and colours that
 * follow the entity. Text never wears a series colour.
 */

import { useMemo } from "react";

import { EChart, escapeHtml, type ChartOption } from "@/components/charts/echart";
import { useI18n, useTheme } from "@/components/providers";
import type { ChartTokens } from "@/lib/theme/tokens";

type Format = (value: number) => string;

interface AxisParam {
  axisValue?: string | number;
  value: unknown;
  color: string;
  seriesName: string;
  dataIndex: number;
  seriesIndex: number;
}

const FONT = '"Inter Variable", system-ui, -apple-system, "Segoe UI", sans-serif';

function base(tokens: ChartTokens): ChartOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: FONT, color: tokens.text2, fontSize: 11 },
    animationDuration: 280,
    animationDurationUpdate: 200,
  };
}

function tooltip(tokens: ChartTokens, extra: Record<string, unknown> = {}) {
  return {
    backgroundColor: tokens.surface,
    borderColor: tokens.grid,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: tokens.text, fontSize: 12, fontFamily: FONT },
    extraCssText: "box-shadow: 0 10px 28px rgba(0,0,0,.22); border-radius: 6px;",
    ...extra,
  };
}

function valueAxis(tokens: ChartTokens, format: Format, extra: Record<string, unknown> = {}) {
  return {
    type: "value",
    scale: true,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: tokens.grid, width: 1, type: "solid" } },
    axisLabel: { color: tokens.muted, formatter: (value: number) => format(value) },
    ...extra,
  };
}

function timeAxis(tokens: ChartTokens, extra: Record<string, unknown> = {}) {
  return {
    type: "time",
    axisLine: { lineStyle: { color: tokens.axis } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: { color: tokens.muted, hideOverlap: true },
    axisPointer: { lineStyle: { color: tokens.axis, width: 1 } },
    ...extra,
  };
}

function legend(tokens: ChartTokens, names: string[], shape: "line" | "rect" = "line") {
  return {
    show: names.length > 1,
    data: names,
    top: 0,
    left: 0,
    icon: shape === "line" ? "rect" : "roundRect",
    itemWidth: shape === "line" ? 14 : 10,
    itemHeight: shape === "line" ? 2 : 10,
    itemGap: 16,
    // The 2px surface ring belongs to dots on the plot, not to the legend keys.
    itemStyle: { borderWidth: 0 },
    textStyle: { color: tokens.text2, fontSize: 11, fontFamily: FONT },
  };
}

function row(color: string, value: string, name: string, muted: string): string {
  return `<div style="display:flex;align-items:center;gap:8px;line-height:18px"><span style="display:inline-block;width:12px;height:2px;border-radius:1px;background:${color}"></span><strong style="font-variant-numeric:tabular-nums;font-weight:600">${escapeHtml(value)}</strong><span style="color:${muted}">${escapeHtml(name)}</span></div>`;
}

function heading(text: string, muted: string): string {
  return `<div style="font-size:11px;color:${muted};margin-bottom:4px">${escapeHtml(text)}</div>`;
}

// ── Time series ──────────────────────────────────────────────────────

export interface TimeLine {
  name: string;
  color: string;
  points: { time: string; value: number | null }[];
  area?: boolean;
}

/** Lines (and washes) over time, one axis only; ``reference`` draws a baseline (e.g. 100). */
export function TimeSeriesChart({
  lines,
  format,
  label,
  height = 300,
  reference,
}: {
  lines: TimeLine[];
  format: Format;
  label: string;
  height?: number;
  reference?: number;
}) {
  const { tokens } = useTheme();
  const { fmt } = useI18n();
  const option = useMemo<ChartOption>(() => {
    const multi = lines.length > 1;
    // End labels while they cannot collide; with more lines the legend, the tooltip and the
    // table next to the chart carry identity (labels stacked apart would detach from lines).
    const endLabels = lines.length === 2;
    return {
      ...base(tokens),
      grid: { left: 4, right: endLabels ? 84 : 16, top: multi ? 32 : 12, bottom: 4, containLabel: true },
      legend: legend(tokens, lines.map((l) => l.name)),
      tooltip: tooltip(tokens, {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: tokens.axis } },
        formatter: (params: AxisParam[]) => {
          const first = params[0];
          if (!first) return "";
          const time = Array.isArray(first.value) ? String(first.value[0]) : String(first.axisValue);
          return (
            heading(fmt.date(time), tokens.muted) +
            params
              .map((p) => {
                const value = Array.isArray(p.value) ? (p.value[1] as number | null) : null;
                return row(p.color, value === null ? "—" : format(value), p.seriesName, tokens.muted);
              })
              .join("")
          );
        },
      }),
      xAxis: timeAxis(tokens),
      yAxis: valueAxis(tokens, format),
      dataZoom: [{ type: "inside", zoomOnMouseWheel: "ctrl", moveOnMouseMove: true }],
      series: lines.map((line, index) => ({
        name: line.name,
        type: "line",
        showSymbol: false,
        symbol: "circle",
        symbolSize: 8,
        sampling: "lttb",
        connectNulls: false,
        lineStyle: { width: 2, color: line.color, cap: "round", join: "round" },
        itemStyle: { color: line.color, borderColor: tokens.surface, borderWidth: 2 },
        areaStyle: line.area ? { color: line.color, opacity: 0.1 } : undefined,
        endLabel: endLabels ? { show: true, formatter: "{a}", color: tokens.text2, fontSize: 11, distance: 6 } : undefined,
        emphasis: { focus: "none", lineStyle: { width: 2 } },
        markLine:
          reference !== undefined && index === 0
            ? {
                silent: true,
                symbol: "none",
                label: { show: false },
                lineStyle: { color: tokens.axis, width: 1, type: "solid" },
                data: [{ yAxis: reference }],
              }
            : undefined,
        data: line.points.map((p) => [p.time, p.value]),
      })),
    };
  }, [lines, format, tokens, fmt, reference]);
  return <EChart option={option} height={height} label={label} />;
}

// ── Prices ───────────────────────────────────────────────────────────

export interface PriceBar {
  time: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
}

/** Candles (hollow up, filled down: direction never by colour alone) or a close line, with volume below. */
export function PriceChart({
  bars,
  format,
  label,
  color,
  height = 380,
  labels,
}: {
  bars: PriceBar[];
  format: Format;
  label: string;
  color: string;
  height?: number;
  labels: { price: string; volume: string; open: string; high: string; low: string; close: string };
}) {
  const { tokens } = useTheme();
  const { fmt } = useI18n();
  const option = useMemo<ChartOption>(() => {
    const ohlc = bars.length > 0 && bars.every((b) => b.open != null && b.high != null && b.low != null);
    const volume = bars.some((b) => (b.volume ?? 0) > 0);
    const times = bars.map((b) => b.time);
    const priceGrid = volume ? { left: 4, right: 12, top: 12, height: "66%", containLabel: true } : { left: 4, right: 12, top: 12, bottom: 4, containLabel: true };
    const grids = volume ? [priceGrid, { left: 4, right: 12, top: "78%", bottom: 4, containLabel: true }] : [priceGrid];
    const category = (gridIndex: number, show: boolean) => ({
      type: "category",
      gridIndex,
      data: times,
      boundaryGap: ohlc,
      axisLine: { lineStyle: { color: tokens.axis } },
      axisTick: { show: false },
      axisLabel: { show, color: tokens.muted, hideOverlap: true, formatter: (value: string) => fmt.monthYear(value) },
      axisPointer: { lineStyle: { color: tokens.axis } },
    });
    const series: unknown[] = [
      ohlc
        ? {
            name: labels.price,
            type: "candlestick",
            xAxisIndex: 0,
            yAxisIndex: 0,
            barMaxWidth: 12,
            itemStyle: { color: tokens.surface, color0: tokens.down, borderColor: tokens.up, borderColor0: tokens.down, borderWidth: 1 },
            data: bars.map((b) => [b.open, b.close, b.low, b.high]),
          }
        : {
            name: labels.price,
            type: "line",
            xAxisIndex: 0,
            yAxisIndex: 0,
            showSymbol: false,
            sampling: "lttb",
            lineStyle: { width: 2, color },
            areaStyle: { color, opacity: 0.1 },
            itemStyle: { color },
            data: bars.map((b) => b.close),
          },
    ];
    if (volume) {
      series.push({
        name: labels.volume,
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 12,
        itemStyle: { color: tokens.axis, borderRadius: [2, 2, 0, 0] },
        data: bars.map((b) => b.volume ?? null),
      });
    }
    return {
      ...base(tokens),
      grid: grids,
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      tooltip: tooltip(tokens, {
        trigger: "axis",
        axisPointer: { type: "line" },
        formatter: (params: AxisParam[]) => {
          const first = params[0];
          if (!first) return "";
          const bar = bars[first.dataIndex];
          if (!bar) return "";
          const lines = ohlc
            ? [
                row(tokens.axis, format(bar.open ?? Number.NaN), labels.open, tokens.muted),
                row(tokens.axis, format(bar.high ?? Number.NaN), labels.high, tokens.muted),
                row(tokens.axis, format(bar.low ?? Number.NaN), labels.low, tokens.muted),
                row(bar.close >= (bar.open ?? bar.close) ? tokens.up : tokens.down, format(bar.close), labels.close, tokens.muted),
              ]
            : [row(color, format(bar.close), labels.close, tokens.muted)];
          if (volume && bar.volume != null) lines.push(row(tokens.axis, fmt.compact(bar.volume), labels.volume, tokens.muted));
          return heading(fmt.date(bar.time), tokens.muted) + lines.join("");
        },
      }),
      xAxis: volume ? [category(0, false), category(1, true)] : [category(0, true)],
      yAxis: volume
        ? [valueAxis(tokens, format, { gridIndex: 0 }), valueAxis(tokens, (v) => fmt.compact(v), { gridIndex: 1, splitNumber: 2, scale: false })]
        : [valueAxis(tokens, format, { gridIndex: 0 })],
      dataZoom: [{ type: "inside", xAxisIndex: volume ? [0, 1] : [0], zoomOnMouseWheel: "ctrl", moveOnMouseMove: true }],
      series,
    };
  }, [bars, format, labels, color, tokens, fmt]);
  return <EChart option={option} height={height} label={label} />;
}

// ── Correlation ──────────────────────────────────────────────────────

/** A diverging heat map of −1…+1 around a neutral grey, each cell labelled while it fits. */
export function CorrelationHeatmap({
  labels: names,
  values,
  label,
  height,
}: {
  labels: string[];
  values: (number | null)[][];
  label: string;
  height?: number;
}) {
  const { tokens } = useTheme();
  const { fmt } = useI18n();
  const size = height ?? Math.max(220, 56 * names.length + 72);
  const option = useMemo<ChartOption>(() => {
    const data: [number, number, number | null][] = [];
    values.forEach((rowValues, y) => rowValues.forEach((value, x) => data.push([x, y, value])));
    const axis = (inverse: boolean) => ({
      type: "category",
      data: names,
      inverse,
      axisLine: { show: false },
      axisTick: { show: false },
      splitArea: { show: false },
      axisLabel: { color: tokens.text2, fontFamily: '"JetBrains Mono Variable", monospace', fontSize: 11 },
    });
    return {
      ...base(tokens),
      grid: { left: 4, right: 8, top: 4, bottom: 44, containLabel: true },
      tooltip: tooltip(tokens, {
        trigger: "item",
        formatter: (p: { value: [number, number, number | null] }) => {
          const [x, y, value] = p.value;
          return heading(`${names[y] ?? ""} × ${names[x] ?? ""}`, tokens.muted) + `<strong style="font-variant-numeric:tabular-nums">${value === null ? "—" : fmt.number(value, 2)}</strong>`;
        },
      }),
      xAxis: axis(false),
      yAxis: axis(true),
      visualMap: {
        min: -1,
        max: 1,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 160,
        text: ["+1", "−1"],
        textStyle: { color: tokens.muted, fontSize: 11 },
        inRange: { color: [tokens.diverging.negative, tokens.diverging.neutral, tokens.diverging.positive] },
      },
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: tokens.surface, borderWidth: 2, borderRadius: 3 },
          label: { show: names.length <= 8, color: tokens.text, fontSize: 11, formatter: (p: { value: [number, number, number | null] }) => (p.value[2] === null ? "—" : fmt.number(p.value[2], 2)) },
          emphasis: { itemStyle: { borderColor: tokens.text, borderWidth: 1 } },
        },
      ],
    };
  }, [names, values, tokens, fmt]);
  return <EChart option={option} height={size} label={label} />;
}

// ── Fans (Monte Carlo, savings plans) ────────────────────────────────

export interface FanBand {
  name: string;
  lower: number[];
  upper: number[];
  opacity: number;
}

/** Percentile bands as stacked washes of one hue, the median as a 2px line, extras as lines. */
export function FanChart({
  steps,
  bands,
  median,
  medianName,
  extras = [],
  goal,
  format,
  stepLabel,
  axisLabel,
  axisName,
  label,
  height = 340,
}: {
  steps: number[];
  bands: FanBand[];
  median: number[];
  medianName: string;
  extras?: { name: string; color: string; values: number[] }[];
  goal?: { value: number; name: string };
  format: Format;
  /** The step as the tooltip names it ("Session 28", "3 years"). */
  stepLabel: (step: number) => string;
  /** The step on the axis; ``null`` hides that tick (defaults to ``stepLabel``). */
  axisLabel?: (step: number) => string | null;
  axisName?: string;
  label: string;
  height?: number;
}) {
  const { tokens } = useTheme();
  const option = useMemo<ChartOption>(() => {
    const hue = tokens.series[0] ?? tokens.text;
    const series: unknown[] = [];
    bands.forEach((band, index) => {
      series.push({
        name: `${band.name}-base`,
        type: "line",
        stack: `band${index}`,
        data: band.lower,
        lineStyle: { opacity: 0 },
        showSymbol: false,
        silent: true,
        tooltip: { show: false },
      });
      series.push({
        name: band.name,
        type: "line",
        stack: `band${index}`,
        data: band.upper.map((upper, i) => upper - (band.lower[i] ?? 0)),
        lineStyle: { opacity: 0 },
        showSymbol: false,
        areaStyle: { color: hue, opacity: band.opacity },
        itemStyle: { color: hue, opacity: band.opacity * 2 },
        silent: true,
      });
    });
    series.push({
      name: medianName,
      type: "line",
      data: median,
      showSymbol: false,
      lineStyle: { width: 2, color: hue },
      itemStyle: { color: hue },
      markLine: goal
        ? {
            silent: true,
            symbol: "none",
            lineStyle: { color: tokens.text2, width: 1, type: "solid" },
            label: { formatter: goal.name, color: tokens.text2, position: "insideEndTop", fontSize: 11 },
            data: [{ yAxis: goal.value }],
          }
        : undefined,
    });
    extras.forEach((extra) =>
      series.push({
        name: extra.name,
        type: "line",
        data: extra.values,
        showSymbol: false,
        lineStyle: { width: 2, color: extra.color },
        itemStyle: { color: extra.color },
      }),
    );
    const names = [...bands.map((b) => b.name), medianName, ...extras.map((e) => e.name)];
    return {
      ...base(tokens),
      grid: { left: 4, right: 16, top: 32, bottom: axisName ? 24 : 4, containLabel: true },
      legend: { ...legend(tokens, names, "rect"), data: names.map((name) => ({ name, icon: name === medianName || extras.some((e) => e.name === name) ? "rect" : "roundRect", itemStyle: undefined })) },
      tooltip: tooltip(tokens, {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: tokens.axis } },
        formatter: (params: AxisParam[]) => {
          const first = params[0];
          if (!first) return "";
          const i = first.dataIndex;
          const lines: string[] = [];
          const outer = bands[0];
          const inner = bands[1];
          if (outer) lines.push(row(hue, `${format(outer.lower[i] ?? 0)} – ${format(outer.upper[i] ?? 0)}`, outer.name, tokens.muted));
          if (inner) lines.push(row(hue, `${format(inner.lower[i] ?? 0)} – ${format(inner.upper[i] ?? 0)}`, inner.name, tokens.muted));
          lines.push(row(hue, format(median[i] ?? 0), medianName, tokens.muted));
          extras.forEach((e) => lines.push(row(e.color, format(e.values[i] ?? 0), e.name, tokens.muted)));
          if (goal) lines.push(row(tokens.text2, format(goal.value), goal.name, tokens.muted));
          return heading(stepLabel(steps[i] ?? i), tokens.muted) + lines.join("");
        },
      }),
      xAxis: {
        type: "category",
        data: steps,
        boundaryGap: false,
        name: axisName,
        nameLocation: "middle",
        nameGap: 26,
        nameTextStyle: { color: tokens.muted, fontSize: 11 },
        axisLine: { lineStyle: { color: tokens.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: tokens.muted,
          hideOverlap: true,
          interval: axisLabel ? (_index: number, value: string) => axisLabel(Number(value)) !== null : "auto",
          formatter: (value: string) => (axisLabel ? axisLabel(Number(value)) ?? "" : stepLabel(Number(value))),
        },
      },
      yAxis: valueAxis(tokens, format),
      series,
    };
  }, [steps, bands, median, medianName, extras, goal, format, stepLabel, axisLabel, axisName, tokens]);
  return <EChart option={option} height={height} label={label} />;
}

// ── Distribution ─────────────────────────────────────────────────────

/** A histogram with threshold markers (VaR, CVaR, initial value) labelled on the chart. */
export function HistogramChart({
  bins,
  markers,
  format,
  label,
  height = 300,
}: {
  bins: { lower: number; upper: number; count: number }[];
  markers: { value: number; name: string; color: string }[];
  format: Format;
  label: string;
  height?: number;
}) {
  const { tokens } = useTheme();
  const { fmt } = useI18n();
  const option = useMemo<ChartOption>(() => {
    const hue = tokens.series[0] ?? tokens.text;
    const index = (value: number) => {
      const found = bins.findIndex((bin) => value >= bin.lower && value < bin.upper);
      return found === -1 ? (value < (bins[0]?.lower ?? 0) ? 0 : bins.length - 1) : found;
    };
    return {
      ...base(tokens),
      grid: { left: 4, right: 16, top: 28, bottom: 4, containLabel: true },
      tooltip: tooltip(tokens, {
        trigger: "item",
        formatter: (p: { dataIndex: number }) => {
          const bin = bins[p.dataIndex];
          if (!bin) return "";
          return heading(`${format(bin.lower)} – ${format(bin.upper)}`, tokens.muted) + `<strong style="font-variant-numeric:tabular-nums">${fmt.number(bin.count, 0)}</strong>`;
        },
      }),
      xAxis: {
        type: "category",
        data: bins.map((bin) => (bin.lower + bin.upper) / 2),
        axisLine: { lineStyle: { color: tokens.axis } },
        axisTick: { show: false },
        axisLabel: { color: tokens.muted, hideOverlap: true, formatter: (value: string) => format(Number(value)) },
      },
      yAxis: valueAxis(tokens, (v) => fmt.number(v, 0), { scale: false }),
      series: [
        {
          type: "bar",
          data: bins.map((bin) => bin.count),
          barCategoryGap: 2,
          barMaxWidth: 24,
          itemStyle: { color: hue, borderRadius: [3, 3, 0, 0] },
          emphasis: { itemStyle: { color: tokens.series[0], opacity: 0.85 } },
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            data: markers.map((marker) => ({
              xAxis: index(marker.value),
              lineStyle: { color: marker.color, width: 2, type: "solid" },
            })),
          },
        },
      ],
    };
  }, [bins, markers, format, tokens, fmt]);
  return (
    <div className="flex flex-col gap-2">
      <EChart option={option} height={height} label={label} />
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
        {markers.map((marker) => (
          <li key={marker.name} className="flex items-center gap-2">
            <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: marker.color }} />
            <strong className="tabular font-semibold text-text">{format(marker.value)}</strong>
            <span className="text-text-2">{marker.name}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Bars ─────────────────────────────────────────────────────────────

/** Horizontal grouped bars (≤ 3 series), values at the tips, 2px gap between neighbours. */
export function GroupedBars({
  categories,
  series,
  format,
  label,
  height,
}: {
  categories: string[];
  series: { name: string; color: string; values: number[] }[];
  format: Format;
  label: string;
  height?: number;
}) {
  const { tokens } = useTheme();
  const size = height ?? Math.max(180, categories.length * series.length * 18 + categories.length * 14 + 48);
  const option = useMemo<ChartOption>(
    () => ({
      ...base(tokens),
      grid: { left: 4, right: 56, top: series.length > 1 ? 30 : 8, bottom: 4, containLabel: true },
      legend: legend(tokens, series.map((s) => s.name), "rect"),
      tooltip: tooltip(tokens, {
        trigger: "axis",
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,0.08)" } },
        formatter: (params: AxisParam[]) => {
          const first = params[0];
          if (!first) return "";
          return heading(String(first.axisValue ?? ""), tokens.muted) + params.map((p) => row(p.color, format(Number(p.value)), p.seriesName, tokens.muted)).join("");
        },
      }),
      xAxis: valueAxis(tokens, format, { scale: false }),
      yAxis: {
        type: "category",
        data: categories,
        inverse: true,
        axisLine: { lineStyle: { color: tokens.axis } },
        axisTick: { show: false },
        axisLabel: { color: tokens.text2, fontFamily: '"JetBrains Mono Variable", monospace', fontSize: 11 },
      },
      series: series.map((s) => ({
        name: s.name,
        type: "bar",
        data: s.values,
        barMaxWidth: 14,
        barGap: "20%",
        itemStyle: { color: s.color, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: tokens.text2, fontSize: 11, formatter: (p: { value: number }) => format(p.value) },
      })),
    }),
    [categories, series, format, tokens],
  );
  return <EChart option={option} height={size} label={label} />;
}

// ── Frontier ─────────────────────────────────────────────────────────

export interface FrontierPoint {
  volatility: number;
  expectedReturn: number;
}

/** Risk–return plane: frontier line, holdings as labelled dots, optimal portfolios as marked points. */
export function FrontierChart({
  frontier,
  assets,
  highlights,
  names,
  format,
  label,
  height = 380,
}: {
  frontier: FrontierPoint[];
  assets: (FrontierPoint & { symbol: string })[];
  highlights: (FrontierPoint & { name: string; color: string; shape: "circle" | "diamond" | "triangle" })[];
  names: { frontier: string; assets: string; volatility: string; expectedReturn: string };
  format: Format;
  label: string;
  height?: number;
}) {
  const { tokens } = useTheme();
  const option = useMemo<ChartOption>(() => {
    const frontierColor = tokens.series[0] ?? tokens.text;
    const pointTooltip = (name: string, point: FrontierPoint) =>
      heading(name, tokens.muted) +
      row(tokens.axis, format(point.volatility), names.volatility, tokens.muted) +
      row(tokens.axis, format(point.expectedReturn), names.expectedReturn, tokens.muted);
    const legendNames = [names.frontier, ...highlights.map((h) => h.name), names.assets];
    return {
      ...base(tokens),
      grid: { left: 24, right: 24, top: 36, bottom: 24, containLabel: true },
      legend: { ...legend(tokens, legendNames, "rect"), icon: undefined },
      tooltip: tooltip(tokens, { trigger: "item" }),
      xAxis: valueAxis(tokens, format, { name: names.volatility, nameLocation: "middle", nameGap: 26, nameTextStyle: { color: tokens.muted, fontSize: 11 } }),
      yAxis: valueAxis(tokens, format, { name: names.expectedReturn, nameLocation: "middle", nameRotate: 90, nameGap: 44, nameTextStyle: { color: tokens.muted, fontSize: 11 } }),
      series: [
        {
          name: names.frontier,
          type: "line",
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: frontierColor },
          itemStyle: { color: frontierColor },
          data: frontier.map((p) => [p.volatility, p.expectedReturn]),
          tooltip: { show: false },
          z: 2,
        },
        {
          name: names.assets,
          type: "scatter",
          symbolSize: 9,
          itemStyle: { color: tokens.muted, borderColor: tokens.surface, borderWidth: 2 },
          label: { show: true, position: "right", color: tokens.text2, fontSize: 11, formatter: (p: { dataIndex: number }) => assets[p.dataIndex]?.symbol ?? "" },
          // A holding's label gives way to an optimal portfolio's; its tooltip keeps it.
          labelLayout: { hideOverlap: true },
          tooltip: { formatter: (p: { dataIndex: number }) => { const a = assets[p.dataIndex]; return a ? pointTooltip(a.symbol, a) : ""; } },
          data: assets.map((a) => [a.volatility, a.expectedReturn]),
          z: 3,
        },
        ...highlights.map((h, index) => ({
          name: h.name,
          type: "scatter",
          symbol: h.shape,
          symbolSize: h.shape === "circle" ? 12 : 14,
          itemStyle: { color: h.color, borderColor: tokens.surface, borderWidth: 2 },
          label: { show: true, position: index === 0 ? "bottom" : "top", distance: 8, color: tokens.text, fontSize: 11, fontWeight: 600, textBorderColor: tokens.surface, textBorderWidth: 3, formatter: h.name },
          tooltip: { formatter: () => pointTooltip(h.name, h) },
          data: [[h.volatility, h.expectedReturn]],
          z: 4,
        })),
      ],
    };
  }, [frontier, assets, highlights, names, format, tokens]);
  return <EChart option={option} height={height} label={label} />;
}

// ── Sparkline ────────────────────────────────────────────────────────

/** A 12-point-style trend: the line in the de-emphasis hue, the latest value in the accent. */
export function Sparkline({ values, label, height = 40 }: { values: number[]; label: string; height?: number }) {
  const { tokens } = useTheme();
  const option = useMemo<ChartOption>(() => {
    const accent = tokens.series[0] ?? tokens.text;
    const last = values.length - 1;
    return {
      ...base(tokens),
      animation: false,
      grid: { left: 2, right: 6, top: 4, bottom: 4 },
      xAxis: { type: "category", show: false, data: values.map((_, i) => i), boundaryGap: false },
      yAxis: { type: "value", show: false, scale: true },
      series: [
        {
          type: "line",
          data: values,
          showSymbol: false,
          lineStyle: { width: 1.5, color: tokens.muted },
          areaStyle: { color: tokens.muted, opacity: 0.08 },
          silent: true,
          markPoint: last >= 0 ? { symbol: "circle", symbolSize: 7, itemStyle: { color: accent, borderColor: tokens.surface, borderWidth: 2 }, label: { show: false }, data: [{ coord: [last, values[last]] }] } : undefined,
        },
      ],
    };
  }, [values, tokens]);
  return <EChart option={option} height={height} label={label} />;
}
