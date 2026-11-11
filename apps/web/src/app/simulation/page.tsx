"use client";

import { useMemo, useState, type FormEvent } from "react";

import { FanChart, HistogramChart } from "@/components/charts/charts";
import { PortfolioSummary } from "@/components/portfolio/builder";
import { useI18n, useTheme } from "@/components/providers";
import { Button, Card, Field, Input, PageHeader, ProblemAlert, Refreshing, Select, Skeleton, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { useSimulation } from "@/lib/api/queries";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";

type Model = Schemas["SimulationModel"];
type Drift = "historical" | "zero" | "risk_free";

interface Parameters {
  model: Model;
  n_paths: number;
  horizon: number;
  drift: Drift;
  seed: number;
  initial_value: number;
}

const DEFAULTS: Parameters = { model: "gbm", n_paths: 5_000, horizon: 252, drift: "historical", seed: 42, initial_value: 10_000 };

export default function SimulationPage() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const draft = usePortfolio((state) => state.draft);
  const [form, setForm] = useState<Parameters>(DEFAULTS);
  const [submitted, setSubmitted] = useState<Parameters>(DEFAULTS);
  const request = useMemo<Schemas["SimulationIn"]>(() => ({ portfolio: toPortfolioIn(draft), ...submitted }), [draft, submitted]);
  const simulation = useSimulation(request);
  const data = simulation.data;
  const currency = draft.baseCurrency ?? "EUR";
  const money = useMemo(() => (v: number) => fmt.money(v, currency), [fmt, currency]);
  const stepLabel = useMemo(() => (step: number) => `${t("simulation.session")} ${step}`, [t]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(form);
  };
  const set = <K extends keyof Parameters>(key: K, value: Parameters[K]) => setForm((current) => ({ ...current, [key]: value }));

  const fan = data?.fan ?? [];
  // About eight round ticks on the axis (0, 30, 60…), whatever the horizon.
  const tick = Math.max(1, Math.round((data?.horizon ?? 252) / 8 / 5) * 5);
  const lossValue = (fraction: number | null | undefined) => (fraction == null || !data ? null : data.initial_value * (1 - fraction));
  const var95 = data?.value_at_risk.find((v) => v.level === 0.95);
  const cvar95 = data?.conditional_value_at_risk.find((v) => v.level === 0.95);

  return (
    <>
      <PageHeader title={t("simulation.title")} subtitle={t("simulation.subtitle")} />
      <div className="mb-6">
        <PortfolioSummary />
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card title={t("simulation.parameters")} subtitle={t("simulation.note")}>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            <Field label={t("simulation.model")} htmlFor="sim-model">
              <Select id="sim-model" value={form.model} onChange={(e) => set("model", e.target.value as Model)}>
                <option value="gbm">{t("simulation.model.gbm")}</option>
                <option value="student_t">{t("simulation.model.student_t")}</option>
                <option value="bootstrap">{t("simulation.model.bootstrap")}</option>
              </Select>
            </Field>
            <Field label={t("simulation.drift")} htmlFor="sim-drift">
              <Select id="sim-drift" value={form.drift} onChange={(e) => set("drift", e.target.value as Drift)}>
                <option value="historical">{t("simulation.drift.historical")}</option>
                <option value="zero">{t("simulation.drift.zero")}</option>
                <option value="risk_free">{t("simulation.drift.risk_free")}</option>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("simulation.paths")} htmlFor="sim-paths">
                <Input id="sim-paths" type="number" min={100} max={20_000} step={100} value={form.n_paths} onChange={(e) => set("n_paths", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.horizon")} htmlFor="sim-horizon">
                <Input id="sim-horizon" type="number" min={1} max={2_520} value={form.horizon} onChange={(e) => set("horizon", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.initial")} htmlFor="sim-initial">
                <Input id="sim-initial" type="number" min={1} step={1_000} value={form.initial_value} onChange={(e) => set("initial_value", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.seed")} htmlFor="sim-seed">
                <Input id="sim-seed" type="number" min={0} value={form.seed} onChange={(e) => set("seed", Number(e.target.value))} className="tabular" />
              </Field>
            </div>
            <Button type="submit" variant="primary">
              {t("common.run")}
            </Button>
          </form>
        </Card>

        <div className="flex flex-col gap-6">
          {simulation.isError ? <ProblemAlert error={simulation.error} onRetry={() => void simulation.refetch()} /> : null}
          {!data ? (
            simulation.isError ? null : (
              <>
                <Skeleton className="h-[110px]" />
                <Skeleton className="h-[360px]" />
              </>
            )
          ) : (
            <Refreshing active={simulation.isFetching}>
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
                <div className="grid gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]">
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
            </Refreshing>
          )}
        </div>
      </div>
    </>
  );
}
