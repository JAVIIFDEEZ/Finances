"use client";

import { useMemo, useState, type FormEvent } from "react";

import { FanChart } from "@/components/charts/charts";
import { PortfolioSummary } from "@/components/portfolio/builder";
import { useI18n, useTheme } from "@/components/providers";
import { Button, Card, Field, Input, PageHeader, ProblemAlert, Refreshing, Select, Skeleton, Stat } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { usePlan } from "@/lib/api/queries";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { seriesColor } from "@/lib/theme/tokens";

interface Plan {
  years: number;
  initial: number;
  contribution: number;
  growth: number;
  inflation: number;
  goal: number;
  returnMode: "assumed" | "historical";
  expectedReturn: number;
}

/** Prudent by default: 5 % a year, not the portfolio's recent history projected for decades. */
const DEFAULTS: Plan = {
  years: 20,
  initial: 10_000,
  contribution: 300,
  growth: 2,
  inflation: 2,
  goal: 150_000,
  returnMode: "assumed",
  expectedReturn: 5,
};

function NumberField({ id, label, value, onChange, step = 1, suffix, min }: { id: string; label: string; value: number; onChange: (value: number) => void; step?: number; suffix?: string; min?: number }) {
  return (
    <Field label={label} htmlFor={id}>
      <div className="relative">
        <Input id={id} type="number" step={step} min={min} value={value} onChange={(e) => onChange(Number(e.target.value))} className="pr-8 tabular" />
        {suffix ? <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted">{suffix}</span> : null}
      </div>
    </Field>
  );
}

export default function PlanningPage() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const draft = usePortfolio((state) => state.draft);
  const [form, setForm] = useState<Plan>(DEFAULTS);
  const [submitted, setSubmitted] = useState<Plan>(DEFAULTS);
  const request = useMemo<Schemas["PlanIn"]>(
    () => ({
      portfolio: toPortfolioIn(draft),
      years: submitted.years,
      initial: submitted.initial,
      contribution: submitted.contribution,
      contribution_growth: submitted.growth / 100,
      inflation: submitted.inflation / 100,
      goal: submitted.goal > 0 ? submitted.goal : null,
      expected_return: submitted.returnMode === "assumed" ? submitted.expectedReturn / 100 : null,
      n_paths: 5_000,
    }),
    [draft, submitted],
  );
  const plan = usePlan(request);
  const data = plan.data;
  const currency = data?.currency ?? draft.baseCurrency ?? "EUR";
  const money = useMemo(() => (v: number) => fmt.money(v, currency), [fmt, currency]);
  const monthLabel = useMemo(() => (month: number) => (month % 12 === 0 ? `${month / 12} ${t("common.years")}` : `${month} ${t("common.months")}`), [t]);
  const set = <K extends keyof Plan>(key: K, value: Plan[K]) => setForm((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(form);
  };
  const fan = data?.fan ?? [];

  return (
    <>
      <PageHeader title={t("planning.title")} subtitle={t("planning.subtitle")} />
      <div className="mb-6">
        <PortfolioSummary />
      </div>
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card title={t("simulation.parameters")}>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            <div className="grid grid-cols-2 gap-3">
              <NumberField id="plan-years" label={t("planning.years")} value={form.years} onChange={(v) => set("years", v)} min={1} />
              <NumberField id="plan-initial" label={t("planning.initial")} value={form.initial} onChange={(v) => set("initial", v)} step={1_000} min={0} />
              <NumberField id="plan-contribution" label={t("planning.contribution")} value={form.contribution} onChange={(v) => set("contribution", v)} step={50} />
              <NumberField id="plan-growth" label={t("planning.growth")} value={form.growth} onChange={(v) => set("growth", v)} step={0.5} suffix="%" />
              <NumberField id="plan-inflation" label={t("planning.inflation")} value={form.inflation} onChange={(v) => set("inflation", v)} step={0.5} suffix="%" />
              <NumberField id="plan-goal" label={t("planning.goal")} value={form.goal} onChange={(v) => set("goal", v)} step={5_000} min={0} />
            </div>
            <Field label={t("planning.returnMode")} htmlFor="plan-return-mode" hint={t("planning.returnHint")}>
              <Select id="plan-return-mode" value={form.returnMode} onChange={(e) => set("returnMode", e.target.value as Plan["returnMode"])}>
                <option value="assumed">{t("planning.return.assumed")}</option>
                <option value="historical">{t("planning.return.historical")}</option>
              </Select>
            </Field>
            {form.returnMode === "assumed" ? (
              <NumberField id="plan-return" label={t("planning.returnRate")} value={form.expectedReturn} onChange={(v) => set("expectedReturn", v)} step={0.5} suffix="%" />
            ) : null}
            <Button type="submit" variant="primary">
              {t("common.run")}
            </Button>
          </form>
        </Card>
        <div className="flex flex-col gap-6">
          {plan.isError ? <ProblemAlert error={plan.error} onRetry={() => void plan.refetch()} /> : null}
          {!data ? (
            plan.isError ? null : <Skeleton className="h-[460px]" />
          ) : (
            <Refreshing active={plan.isFetching}>
              <div className="flex flex-col gap-6">
                <Card title={t("planning.title")} subtitle={`${data.months} ${t("common.months")} · ${currency}`}>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
                    <Stat label={t("planning.success")} value={fmt.percent(data.probability_of_success ?? null, 0)} />
                    <Stat label={t("planning.medianWealth")} value={money(data.median_terminal_wealth ?? Number.NaN)} />
                    <Stat label={t("planning.required")} value={data.required_contribution == null ? "—" : money(data.required_contribution)} detail={t("planning.contribution")} />
                    <Stat label={t("planning.ruin")} value={fmt.percent(data.probability_of_ruin ?? null, 1)} detail={data.expected_shortfall != null ? `${t("planning.shortfall")} ${money(data.expected_shortfall)}` : undefined} />
                  </div>
                </Card>
                <Card title={t("planning.wealth")}>
                  <FanChart
                    label={t("planning.wealth")}
                    height={380}
                    steps={fan.map((p) => p.month)}
                    bands={[
                      { name: t("simulation.band90"), lower: fan.map((p) => p.p5), upper: fan.map((p) => p.p95), opacity: 0.12 },
                      { name: t("simulation.band50"), lower: fan.map((p) => p.p25), upper: fan.map((p) => p.p75), opacity: 0.22 },
                    ]}
                    median={fan.map((p) => p.p50)}
                    medianName={t("simulation.medianLine")}
                    extras={[{ name: t("planning.contributed"), color: seriesColor(tokens, 1), values: fan.map((p) => p.contributed) }]}
                    goal={data.goal != null ? { value: data.goal, name: t("planning.goal") } : undefined}
                    format={money}
                    stepLabel={monthLabel}
                    axisLabel={(month) => (month % 12 === 0 ? String(month / 12) : null)}
                    axisName={t("planning.yearsAxis")}
                  />
                </Card>
              </div>
            </Refreshing>
          )}
        </div>
      </div>
    </>
  );
}
