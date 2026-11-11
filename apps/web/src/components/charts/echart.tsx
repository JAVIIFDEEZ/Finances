"use client";

import { BarChart, CandlestickChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
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

/** Escape text from the API before it goes into a tooltip's HTML (labels are untrusted). */
export const escapeHtml = (text: string): string => echarts.format.encodeHTML(text);

/**
 * One ECharts canvas: created once, re-optioned when ``option`` changes, resized with its
 * container and disposed on unmount. ``label`` is the accessible description of the chart;
 * every chart also has its numbers in a table or a stat list next to it.
 */
export function EChart({ option, height, label }: { option: ChartOption; height: number; label: string }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const latest = useRef(option);
  const { locale } = useI18n();

  useEffect(() => {
    latest.current = option;
    chart.current?.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [option]);

  // A new language needs a new instance: the locale is fixed when a chart is created.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const instance = echarts.init(element, undefined, { renderer: "canvas", locale: locale.toUpperCase() });
    instance.setOption(latest.current, { notMerge: true });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [locale]);

  return <div ref={container} role="img" aria-label={label} style={{ height, width: "100%" }} />;
}
