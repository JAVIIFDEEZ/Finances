"use client";

import { Check } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { FrontierChart, GroupedBars } from "@/components/charts/charts";
import { PortfolioSummary } from "@/components/portfolio/builder";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, Field, Input, PageHeader, ProblemAlert, Refreshing, Select, Skeleton, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { useOptimization } from "@/lib/api/queries";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { seriesColor } from "@/lib/theme/tokens";

type Objective = Schemas["Objective"];
const OBJECTIVES: readonly Objective[] = ["max_sharpe", "min_variance", "risk_parity", "hrp", "inverse_volatility"];

interface Settings {
  objective: Objective;
  maxWeight: number;
}

export default function OptimizationPage() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const draft = usePortfolio((state) => state.draft);
  const setWeights = usePortfolio((state) => state.setWeights);
  const [form, setForm] = useState<Settings>({ objective: "max_sharpe", maxWeight: 60 });
  const [submitted, setSubmitted] = useState<Settings>(form);
  const [applied, setApplied] = useState(false);
  const request = useMemo<Schemas["OptimizationIn"]>(
    () => ({
      portfolio: toPortfolioIn(draft),
      objective: submitted.objective,
      max_weight: submitted.maxWeight / 100,
      frontier_points: 40,
    }),
    [draft, submitted],
  );
  const optimization = useOptimization(request);
  const data = optimization.data;
  const percent = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);
  const percent1 = useMemo(() => (v: number) => fmt.percent(v, 1), [fmt]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setApplied(false);
    setSubmitted(form);
  };
  const apply = () => {
    if (!data) return;
    setWeights(Object.fromEntries(data.result.weights.map((w) => [w.symbol, w.weight])));
    setApplied(true);
  };

  return (
    <>
      <PageHeader title={t("optimization.title")} subtitle={t("optimization.subtitle")} />
      <div className="mb-6">
        <PortfolioSummary />
      </div>
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card title={t("simulation.parameters")} subtitle={t("optimization.estimates")}>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            <Field label={t("optimization.objective")} htmlFor="opt-objective">
              <Select id="opt-objective" value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value as Objective })}>
                {OBJECTIVES.map((objective) => (
                  <option key={objective} value={objective}>
                    {t(`optimization.objective.${objective}` as "optimization.objective.max_sharpe")}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("optimization.maxWeight")} htmlFor="opt-max">
              <div className="relative">
                <Input id="opt-max" type="number" min={5} max={100} step={5} value={form.maxWeight} onChange={(e) => setForm({ ...form, maxWeight: Number(e.target.value) })} className="pr-6 tabular" />
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted">%</span>
              </div>
            </Field>
            <Button type="submit" variant="primary">
              {t("common.run")}
            </Button>
          </form>
        </Card>

        <div className="flex flex-col gap-6">
          {optimization.isError ? <ProblemAlert error={optimization.error} onRetry={() => void optimization.refetch()} /> : null}
          {!data ? (
            optimization.isError ? null : <Skeleton className="h-[480px]" />
          ) : (
            <Refreshing active={optimization.isFetching}>
              <div className="flex flex-col gap-6">
                <Card
                  title={t(`optimization.objective.${data.objective}` as "optimization.objective.max_sharpe")}
                  subtitle={`${t("metric.observations")}: ${fmt.number(data.observations, 0)}${data.shrinkage != null ? ` · ${t("simulation.shrinkage")} ${fmt.number(data.shrinkage, 2)}` : ""}`}
                  actions={
                    applied ? (
                      <Badge tone="good">{t("optimization.applied")}</Badge>
                    ) : (
                      <Button size="sm" variant="primary" onClick={apply}>
                        <Check aria-hidden className="size-3.5" /> {t("optimization.useWeights")}
                      </Button>
                    )
                  }
                >
                  <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
                    <Stat label={t("optimization.expectedReturn")} value={fmt.percent(data.result.expected_return)} />
                    <Stat label={t("metric.volatility")} value={fmt.percent(data.result.volatility)} />
                    <Stat label={t("metric.sharpe")} value={fmt.number(data.result.sharpe_ratio, 2)} />
                    <Stat label={t("portfolio.effectiveAssets")} value={fmt.number(data.result.effective_number_of_assets, 1)} />
                  </div>
                </Card>
                <Card title={t("optimization.frontier")}>
                  <FrontierChart
                    label={t("optimization.frontier")}
                    format={percent}
                    frontier={data.frontier.map((p) => ({ volatility: p.volatility, expectedReturn: p.expected_return }))}
                    assets={data.assets.filter((a) => a.volatility != null && a.expected_return != null).map((a) => ({ symbol: a.symbol, volatility: a.volatility as number, expectedReturn: a.expected_return as number }))}
                    highlights={[
                      ...(data.minimum_variance?.volatility != null && data.minimum_variance.expected_return != null
                        ? [{ name: t("optimization.minVariance"), color: seriesColor(tokens, 0), shape: "diamond" as const, volatility: data.minimum_variance.volatility, expectedReturn: data.minimum_variance.expected_return }]
                        : []),
                      ...(data.maximum_sharpe?.volatility != null && data.maximum_sharpe.expected_return != null
                        ? [{ name: t("optimization.maxSharpe"), color: seriesColor(tokens, 1), shape: "triangle" as const, volatility: data.maximum_sharpe.volatility, expectedReturn: data.maximum_sharpe.expected_return }]
                        : []),
                      ...(data.result.volatility != null && data.result.expected_return != null && !["min_variance", "max_sharpe"].includes(data.objective)
                        ? [{ name: t("optimization.optimal"), color: seriesColor(tokens, 2), shape: "circle" as const, volatility: data.result.volatility, expectedReturn: data.result.expected_return }]
                        : []),
                    ]}
                    names={{ frontier: t("optimization.frontier"), assets: t("portfolio.holdings"), volatility: t("metric.volatility"), expectedReturn: t("optimization.expectedReturn") }}
                  />
                </Card>
                <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
                  <Card title={t("optimization.weights")}>
                    <GroupedBars
                      label={t("optimization.weights")}
                      format={percent1}
                      categories={data.result.weights.map((w) => w.symbol)}
                      series={[
                        { name: t("optimization.current"), color: seriesColor(tokens, 0), values: data.result.weights.map((w) => w.previous_weight) },
                        { name: t("optimization.optimal"), color: seriesColor(tokens, 1), values: data.result.weights.map((w) => w.weight) },
                      ]}
                    />
                  </Card>
                  <Card title={t("portfolio.contributions")} padded={false}>
                    <table className="w-full text-[13px]">
                      <thead className="text-left text-xs text-text-2">
                        <tr className="border-b hairline">
                          <th className="px-4 py-2.5 font-medium">{t("common.symbol")}</th>
                          <th className="px-4 py-2.5 text-right font-medium">{t("optimization.current")}</th>
                          <th className="px-4 py-2.5 text-right font-medium">{t("optimization.optimal")}</th>
                          <th className="px-4 py-2.5 text-right font-medium">{t("portfolio.riskShare")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.result.weights.map((w) => (
                          <tr key={w.symbol} className="border-b hairline last:border-0">
                            <td className="px-4 py-2.5 font-mono">{w.symbol}</td>
                            <td className="px-4 py-2.5 text-right text-text-2">{fmt.percent(w.previous_weight, 1)}</td>
                            <td className="px-4 py-2.5 text-right font-medium">{fmt.percent(w.weight, 1)}</td>
                            <td className="px-4 py-2.5 text-right">{fmt.percent(data.result.risk_contributions.find((c) => c.symbol === w.symbol)?.share ?? null, 1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Card>
                </div>
              </div>
            </Refreshing>
          )}
        </div>
      </div>
    </>
  );
}
