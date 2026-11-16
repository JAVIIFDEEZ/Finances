"use client";

import { BarChart, CandlestickChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import langEN from "echarts/i18n/langEN-obj.js";
import langES from "echarts/i18n/langES-obj.js";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { useI18n } from "@/components/providers";

echarts.use([
  BarChart,
  CandlestickChart,
  HeatmapChart,
  LineChart,
  ScatterChart,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

// Month and day names of time axes follow the interface language.
type LocaleOption = Parameters<typeof echarts.registerLocale>[1];
echarts.registerLocale("ES", langES as LocaleOption);
echarts.registerLocale("EN", langEN as LocaleOption);

export type ChartOption = echarts.EChartsCoreOption;
export type ChartInstance = echarts.ECharts;

/** Escape text from the API before it goes into a tooltip's HTML (labels are untrusted). */
export const escapeHtml = (text: string): string => echarts.format.encodeHTML(text);

/** The part of the data a chart shows, in percent of its length (``null`` without a zoom). */
export function zoomWindow(chart: ChartInstance): { start: number; end: number } | null {
  const zooms = (chart.getOption() as { dataZoom?: { start?: number; end?: number }[] }).dataZoom;
  const first = zooms?.[0];
  return first?.start === undefined || first.end === undefined ? null : { start: first.start, end: first.end };
}

/**
 * One ECharts canvas: created once, re-optioned when ``option`` changes, resized with its
 * container and disposed on unmount. ``label`` is the accessible description of the chart;
 * every chart also has its numbers in a table or a stat list next to it.
 *
 * ``onReady`` receives each instance once it has its option (a new one per language) and may
 * return a cleanup. While ``zoomKey`` stays the same a new option keeps the zoom the reader
 * chose: adding a line to a chart must not move what they were looking at.
 */
export function EChart({
  option,
  height,
  label,
  onReady,
  zoomKey,
}: {
  option: ChartOption;
  height: number;
  label: string;
  onReady?: (chart: ChartInstance) => void | (() => void);
  zoomKey?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<ChartInstance | null>(null);
  const latest = useRef(option);
  const ready = useRef(onReady);
  const zoomed = useRef(zoomKey);
  const { locale } = useI18n();

  useEffect(() => {
    ready.current = onReady;
  }, [onReady]);

  useEffect(() => {
    latest.current = option;
    const instance = chart.current;
    if (!instance) return;
    const keep = zoomKey !== undefined && zoomKey === zoomed.current ? zoomWindow(instance) : null;
    zoomed.current = zoomKey;
    instance.setOption(option, { notMerge: true, lazyUpdate: keep === null });
    if (keep) instance.dispatchAction({ type: "dataZoom", start: keep.start, end: keep.end });
  }, [option, zoomKey]);

  // A new language needs a new instance: the locale is fixed when a chart is created.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const instance = echarts.init(element, undefined, { renderer: "canvas", locale: locale.toUpperCase() });
    instance.setOption(latest.current, { notMerge: true });
    chart.current = instance;
    const cleanup = ready.current?.(instance);
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      if (typeof cleanup === "function") cleanup();
      instance.dispose();
      chart.current = null;
    };
  }, [locale]);

  return <div ref={container} role="img" aria-label={label} style={{ height, width: "100%" }} />;
}
