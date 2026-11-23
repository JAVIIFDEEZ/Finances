"use client";

import { useMemo } from "react";

import { FanChart, HistogramChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Card, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";

/**
 * What a Monte Carlo simulation produced: tail risk, fan chart, terminal distribution and
 * calibration. The same view for a simulation answered in the request and for one that ran
 * in the background (its job's result is the same document).
 */
export function SimulationResult({ data, currency }: { data: Schemas["SimulationOut"]; currency: string }) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const money = useMemo(() => (v: number) => fmt.money(v, currency), [fmt, currency]);
  const stepLabel = useMemo(() => (step: number) => `${t("simulation.session")} ${step}`, [t]);
  const fan = data.fan;
  // About eight round ticks on the axis (0, 30, 60…), whatever the horizon.
  const tick = Math.max(1, Math.round(data.horizon / 8 / 5) * 5);
  const lossValue = (fraction: number | null | undefined) => (fraction == null ? null : data.initial_value * (1 - fraction));
  const var95 = data.value_at_risk.find((v) => v.level === 0.95);
  const cvar95 = data.conditional_value_at_risk.find((v) => v.level === 0.95);

  return (
    <div className="flex flex-col gap-6">
      <Card title={t("simulation.risk")} subtitle={`${fmt.number(data.n_paths, 0)} ${t("simulation.paths.count")} · ${data.horizon} ${t("common.periods")} · ${t(`simulation.model.${data.model}` as "simulation.model.gbm")}`}>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
          <Stat label={t("simulation.expected")} value={money(data.expected_terminal_value ?? Number.NaN)} />
          <Stat label={t("simulation.median")} value={money(data.median_terminal_value ?? Number.NaN)} />
          <Stat label={t("simulation.probLoss")} value={fmt.percent(data.probability_of_loss, 1)} />
          <Stat label={`${t("simulation.var")} 95 %`} value={fmt.percent(var95?.value ?? null, 1)} detail={`${t("simulation.ci")} ${fmt.percent(var95?.lower ?? null, 1)} – ${fmt.percent(var95?.upper ?? null, 1)}`} />
        </div>
      </Card>
      <Card title={t("simulation.fan")}>
        <FanChart
          label={t("simulation.fan")}
          steps={fan.map((p) => p.period)}
          bands={[
            { name: t("simulation.band90"), lower: fan.map((p) => p.p5), upper: fan.map((p) => p.p95), opacity: 0.12 },
            { name: t("simulation.band50"), lower: fan.map((p) => p.p25), upper: fan.map((p) => p.p75), opacity: 0.22 },
          ]}
          median={fan.map((p) => p.p50)}
          medianName={t("simulation.medianLine")}
          format={money}
          stepLabel={stepLabel}
          axisLabel={(step) => (step % tick === 0 ? String(step) : null)}
          axisName={t("simulation.sessions")}
        />
      </Card>
      <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]">
        <Card title={t("simulation.histogram")}>
          <HistogramChart
            label={t("simulation.histogram")}
            bins={data.terminal_histogram}
            format={money}
            markers={[
              { value: data.initial_value, name: t("simulation.initialMarker"), color: tokens.text2 },
              ...(lossValue(var95?.value) !== null ? [{ value: lossValue(var95?.value) as number, name: "VaR 95 %", color: tokens.warning }] : []),
              ...(lossValue(cvar95?.value) !== null ? [{ value: lossValue(cvar95?.value) as number, name: "CVaR 95 %", color: tokens.critical }] : []),
            ]}
          />
        </Card>
        <Card title={t("simulation.risk")} padded={false}>
          <table className="w-full text-[13px]">
            <thead className="text-left text-xs text-text-2">
              <tr className="border-b hairline">
                <th className="px-4 py-2.5 font-medium" />
                <th className="px-4 py-2.5 font-medium">{t("simulation.level")}</th>
                <th className="px-4 py-2.5 text-right font-medium">{t("common.value")}</th>
                <th className="px-4 py-2.5 text-right font-medium">{t("simulation.ci")}</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  [t("simulation.var"), data.value_at_risk],
                  [t("simulation.cvar"), data.conditional_value_at_risk],
                  [t("simulation.dar"), data.drawdown_at_risk],
                ] as const
              ).flatMap(([name, estimates]) =>
                estimates.map((estimate) => (
                  <tr key={`${name}-${estimate.level}`} className="border-b hairline last:border-0">
                    <td className="px-4 py-2.5 font-medium text-text">{name}</td>
                    <td className="px-4 py-2.5 text-text-2">{fmt.percent(estimate.level, 0)}</td>
                    <td className="px-4 py-2.5 text-right">{fmt.percent(estimate.value ?? null, 2)}</td>
                    <td className="px-4 py-2.5 text-right text-text-2">
                      {estimate.lower != null ? `${fmt.percent(estimate.lower, 2)} – ${fmt.percent(estimate.upper ?? null, 2)}` : "—"}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </Card>
      </div>
      <Card title={t("simulation.calibration")} subtitle={`${t("metric.observations")}: ${fmt.number(data.calibration.observations, 0)}${data.calibration.shrinkage != null ? ` · ${t("simulation.shrinkage")} ${fmt.number(data.calibration.shrinkage, 2)}` : ""}`} padded={false}>
        <table className="w-full text-[13px]">
          <thead className="text-left text-xs text-text-2">
            <tr className="border-b hairline">
              <th className="px-4 py-2.5 font-medium">{t("common.symbol")}</th>
              <th className="px-4 py-2.5 text-right font-medium">{t("common.weight")}</th>
              <th className="px-4 py-2.5 text-right font-medium">{t("simulation.return")}</th>
              <th className="px-4 py-2.5 text-right font-medium">{t("simulation.volatility")}</th>
            </tr>
          </thead>
          <tbody>
            {data.calibration.symbols.map((symbol, index) => (
              <tr key={symbol} className="border-b hairline last:border-0">
                <td className="px-4 py-2.5 font-mono">{symbol}</td>
                <td className="px-4 py-2.5 text-right">{fmt.percent(data.calibration.weights[index] ?? null, 1)}</td>
                <td className="px-4 py-2.5 text-right">{fmt.percent(data.calibration.annual_expected_return[index] ?? null, 1)}</td>
                <td className="px-4 py-2.5 text-right">{fmt.percent(data.calibration.annual_volatility[index] ?? null, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
