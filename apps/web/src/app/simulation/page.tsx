"use client";

import { Hourglass } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { SimulationResult } from "@/components/analysis/simulation";
import { PortfolioSummary } from "@/components/portfolio/builder";
import { useI18n } from "@/components/providers";
import { Button, Card, Field, Input, PageHeader, ProblemAlert, Refreshing, Select, Skeleton } from "@/components/ui";
import type { Schemas } from "@/lib/api/client";
import { problemKind, useSimulation, useSubmitSimulationJob } from "@/lib/api/queries";
import { fill } from "@/lib/i18n/messages";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { JOB_PATHS, needsBackground, REQUEST_PATHS } from "@/lib/util/jobs";

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
  const router = useRouter();
  const draft = usePortfolio((state) => state.draft);
  const [form, setForm] = useState<Parameters>(DEFAULTS);
  const [submitted, setSubmitted] = useState<Parameters>(DEFAULTS);
  const request = useMemo<Schemas["SimulationIn"]>(() => ({ portfolio: toPortfolioIn(draft), ...submitted }), [draft, submitted]);
  const simulation = useSimulation(request);
  const data = simulation.data;
  const currency = draft.baseCurrency ?? "EUR";

  const background = useSubmitSimulationJob();
  const tooLarge = needsBackground(form.n_paths);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!tooLarge) setSubmitted(form);
  };
  // In the background: the job is queued and its page follows it until it finishes.
  const runInBackground = () =>
    background.mutate({ portfolio: toPortfolioIn(draft), ...form }, { onSuccess: (job) => router.push(`/jobs?id=${job.id}`) });
  const set = <K extends keyof Parameters>(key: K, value: Parameters[K]) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <>
      <PageHeader title={t("simulation.title")} subtitle={t("simulation.subtitle")} />
      <div className="mb-6">
        <PortfolioSummary />
      </div>
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
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
                <Input id="sim-paths" type="number" min={100} max={JOB_PATHS} step={100} value={form.n_paths} onChange={(e) => set("n_paths", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.horizon")} htmlFor="sim-horizon">
                <Input id="sim-horizon" type="number" min={1} max={2_520} value={form.horizon} onChange={(e) => set("horizon", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.initial")} htmlFor="sim-initial">
                <Input id="sim-initial" type="number" min={1} step="any" value={form.initial_value} onChange={(e) => set("initial_value", Number(e.target.value))} className="tabular" />
              </Field>
              <Field label={t("simulation.seed")} htmlFor="sim-seed">
                <Input id="sim-seed" type="number" min={0} value={form.seed} onChange={(e) => set("seed", Number(e.target.value))} className="tabular" />
              </Field>
            </div>
            {tooLarge ? (
              <p className="text-xs leading-relaxed text-text-2">
                {fill(t("simulation.tooManyPaths"), { limit: fmt.number(REQUEST_PATHS, 0) })}
              </p>
            ) : null}
            <div className="flex flex-col gap-2">
              <Button type="submit" variant="primary" disabled={tooLarge}>
                {t("common.run")}
              </Button>
              <Button type="button" onClick={runInBackground} disabled={background.isPending}>
                <Hourglass aria-hidden className="size-3.5" />
                {t("simulation.background")}
              </Button>
              <p className="text-xs leading-relaxed text-muted">{fill(t("simulation.backgroundHint"), { limit: fmt.number(JOB_PATHS, 0) })}</p>
            </div>
            {background.isError ? (
              problemKind(background.error) === "persistence-not-configured" ? (
                <p role="alert" className="text-[13px] leading-relaxed text-critical-text">
                  {t("jobs.off")}
                </p>
              ) : (
                <ProblemAlert error={background.error} />
              )
            ) : null}
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
              <SimulationResult data={data} currency={currency} />
            </Refreshing>
          )}
        </div>
      </div>
    </>
  );
}
