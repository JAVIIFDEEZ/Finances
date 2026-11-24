"use client";

import { Hourglass } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { BacktestResult } from "@/components/analysis/backtest";
import { useI18n } from "@/components/providers";
import { Button, Card, Field, Input, PageHeader, ProblemAlert, Refreshing, Select, Skeleton } from "@/components/ui";
import { problemKind, useBacktest, useCostProfiles, useSubmitBacktestJob } from "@/lib/api/queries";
import type { MessageKey } from "@/lib/i18n/messages";
import { backtestRequest, CLASSICS, type BacktestRequest, type ClassicName } from "@/lib/util/backtest";

interface Form {
  symbol: string;
  strategy: ClassicName;
  start: string;
  end: string;
  profile: string;
  commission: string;
  initialCapital: number;
}

const DEFAULTS: Form = { symbol: "SAN.MC", strategy: "sma_crossover", start: "", end: "", profile: "", commission: "", initialCapital: 10_000 };

export default function BacktestPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [form, setForm] = useState<Form>(DEFAULTS);
  const [request, setRequest] = useState<BacktestRequest>(() => backtestRequest(DEFAULTS));
  const backtest = useBacktest(request);
  const profiles = useCostProfiles();
  const background = useSubmitBacktestJob();
  const data = backtest.data;

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setRequest(backtestRequest(form));
  };
  // In the background: the job is queued and its page follows it until it finishes.
  const runInBackground = () => background.mutate(backtestRequest(form), { onSuccess: (job) => router.push(`/jobs?id=${job.id}`) });

  return (
    <>
      <PageHeader title={t("backtest.title")} subtitle={t("backtest.subtitle")} />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card title={t("backtest.parameters")} subtitle={t("backtest.note")}>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            <Field label={t("backtest.symbol")} htmlFor="bt-symbol">
              <Input id="bt-symbol" value={form.symbol} onChange={(e) => set("symbol", e.target.value)} className="font-mono" autoComplete="off" />
            </Field>
            <Field label={t("backtest.strategy")} htmlFor="bt-strategy">
              <Select id="bt-strategy" value={form.strategy} onChange={(e) => set("strategy", e.target.value as ClassicName)}>
                {CLASSICS.map((name) => (
                  <option key={name} value={name}>
                    {t(`backtest.strategy.${name}` as MessageKey)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <Field label={t("backtest.start")} htmlFor="bt-start">
                <Input id="bt-start" type="date" value={form.start} onChange={(e) => set("start", e.target.value)} className="tabular" />
              </Field>
              <Field label={t("backtest.end")} htmlFor="bt-end">
                <Input id="bt-end" type="date" value={form.end} onChange={(e) => set("end", e.target.value)} className="tabular" />
              </Field>
            </div>
            <Field label={t("backtest.profile")} htmlFor="bt-profile">
              <Select id="bt-profile" value={form.profile} onChange={(e) => set("profile", e.target.value)}>
                <option value="">{t("backtest.profile.default")}</option>
                {(profiles.data ?? []).map((profile) => (
                  <option key={profile.key} value={profile.key}>
                    {`${profile.key} · ${profile.name}`}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("backtest.commission")} hint={t("backtest.commissionHint")} htmlFor="bt-commission">
                <Input id="bt-commission" type="number" min={0} step="any" value={form.commission} onChange={(e) => set("commission", e.target.value)} className="tabular" />
              </Field>
              <Field label={t("backtest.capital")} htmlFor="bt-capital">
                <Input id="bt-capital" type="number" min={1} step="any" value={form.initialCapital} onChange={(e) => set("initialCapital", Number(e.target.value))} className="tabular" />
              </Field>
            </div>
            <div className="flex flex-col gap-2">
              <Button type="submit" variant="primary">
                {t("common.run")}
              </Button>
              <Button type="button" onClick={runInBackground} disabled={background.isPending}>
                <Hourglass aria-hidden className="size-3.5" />
                {t("backtest.background")}
              </Button>
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

        <div className="flex min-w-0 flex-col gap-6">
          {backtest.isError ? <ProblemAlert error={backtest.error} onRetry={() => void backtest.refetch()} /> : null}
          {!data ? (
            backtest.isError ? null : (
              <>
                <Skeleton className="h-[110px]" />
                <Skeleton className="h-[320px]" />
              </>
            )
          ) : (
            <Refreshing active={backtest.isFetching}>
              <BacktestResult data={data} />
            </Refreshing>
          )}
        </div>
      </div>
    </>
  );
}
