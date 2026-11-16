/**
 * The pieces every chart shares: the base option, the tooltip, the axes, the legend and the
 * rows of a tooltip. One place, so that all charts read as one system.
 */

import { escapeHtml, type ChartOption } from "@/components/charts/echart";
import type { ChartTokens } from "@/lib/theme/tokens";

export type Format = (value: number) => string;

export interface AxisParam {
  axisValue?: string | number;
  value: unknown;
  color: string;
  seriesName: string;
  dataIndex: number;
  seriesIndex: number;
}

export const FONT = '"Inter Variable", system-ui, -apple-system, "Segoe UI", sans-serif';

export function base(tokens: ChartTokens): ChartOption {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: FONT, color: tokens.text2, fontSize: 11 },
    animationDuration: 280,
    animationDurationUpdate: 200,
  };
}

export function tooltip(tokens: ChartTokens, extra: Record<string, unknown> = {}) {
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

export function valueAxis(tokens: ChartTokens, format: Format, extra: Record<string, unknown> = {}) {
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

export function timeAxis(tokens: ChartTokens, extra: Record<string, unknown> = {}) {
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

export function legend(tokens: ChartTokens, names: string[], shape: "line" | "rect" = "line") {
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

export function row(color: string, value: string, name: string, muted: string): string {
  return `<div style="display:flex;align-items:center;gap:8px;line-height:18px"><span style="display:inline-block;width:12px;height:2px;border-radius:1px;background:${color}"></span><strong style="font-variant-numeric:tabular-nums;font-weight:600">${escapeHtml(value)}</strong><span style="color:${muted}">${escapeHtml(name)}</span></div>`;
}

export function heading(text: string, muted: string): string {
  return `<div style="font-size:11px;color:${muted};margin-bottom:4px">${escapeHtml(text)}</div>`;
}
