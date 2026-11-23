"use client";

import { Ban, Eye, Hourglass, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { SimulationResult } from "@/components/analysis/simulation";
import { useI18n } from "@/components/providers";
import { Badge, Button, Card, PageHeader, ProblemAlert, Skeleton, cn } from "@/components/ui";
import { problemKind, useCancelJob, useDeleteJob, useJob, useJobs } from "@/lib/api/queries";
import { fill, type MessageKey } from "@/lib/i18n/messages";
import { canCancel, canDelete, isFinished, runSeconds, statusTone, waitingForWorker, type Job, type SimulationJob } from "@/lib/util/jobs";

const STATUS: Record<Job["status"], MessageKey> = {
  queued: "jobs.status.queued",
  running: "jobs.status.running",
  succeeded: "jobs.status.succeeded",
  failed: "jobs.status.failed",
  cancelled: "jobs.status.cancelled",
};

const STAGES: Record<string, MessageKey> = {
  loading: "jobs.stage.loading",
  simulating: "jobs.stage.simulating",
  summarising: "jobs.stage.summarising",
};

function useStage(): (stage: string | null) => string | null {
  const { t } = useI18n();
  return (stage) => (stage === null ? null : STAGES[stage] ? t(STAGES[stage] as MessageKey) : stage);
}

/** How far a job is: a bar with its percentage while it runs. */
function ProgressBar({ job }: { job: Job }) {
  const { t, fmt } = useI18n();
  const stage = useStage()(job.stage);
  const value = job.progress;
  return (
    <div className="flex flex-col gap-1">
      <div
        role="progressbar"
        aria-label={t("jobs.progress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value === null ? undefined : Math.round(value * 100)}
        className="h-1.5 overflow-hidden rounded-full bg-surface-2"
      >
        <div className={cn("h-full rounded-full bg-accent transition-[width]", value === null && "w-1/4 animate-pulse")} style={value === null ? undefined : { width: `${value * 100}%` }} />
      </div>
      <p className="text-xs text-text-2 tabular">
        {stage ?? t("jobs.starting")}
        {value !== null ? ` · ${fmt.percent(value, 0)}` : null}
      </p>
    </div>
  );
}

function JobList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const { t, fmt } = useI18n();
  const jobs = useJobs();
  const items = jobs.data?.items ?? [];
  return (
    <Card title={t("jobs.list")} subtitle={t("jobs.listNote")}>
      {jobs.isLoading ? (
        <Skeleton className="h-32" />
      ) : jobs.isError ? (
        <ProblemAlert error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : items.length === 0 ? (
        <p className="text-[13px] leading-relaxed text-text-2">
          {t("jobs.empty")}{" "}
          <Link href="/simulation" className="font-medium text-accent-strong underline-offset-2 hover:underline">
            {t("jobs.emptyLink")}
          </Link>
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-[var(--border)]">
          {items.map((job) => (
            <li
              key={job.id}
              aria-current={job.id === selected ? "true" : undefined}
              className={cn("-mx-2 flex flex-col gap-2 rounded-md px-2 py-3", job.id === selected && "bg-accent-wash")}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-text">{t(`jobs.kind.${job.kind}` as MessageKey)}</p>
                  <p className="text-xs text-muted tabular">{fmt.dateTime(job.created_at)}</p>
                </div>
                <Badge tone={statusTone(job.status)}>{t(STATUS[job.status])}</Badge>
              </div>
              {!isFinished(job.status) ? <ProgressBar job={job} /> : null}
              <div>
                <Button size="sm" onClick={() => onSelect(job.id)} aria-label={fill(t("jobs.openLabel"), { when: fmt.dateTime(job.created_at) })} aria-pressed={job.id === selected}>
                  <Eye aria-hidden className="size-3.5" />
                  {t("jobs.open")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Parameters({ job }: { job: SimulationJob }) {
  const { t, fmt } = useI18n();
  const parameters = job.parameters;
  const rows: [string, string][] = [
    [t("simulation.paths"), fmt.number(parameters.n_paths ?? null, 0)],
    [t("simulation.horizon"), fmt.number(parameters.horizon ?? null, 0)],
    [t("simulation.model"), t(`simulation.model.${parameters.model ?? "gbm"}` as MessageKey)],
    [t("jobs.holdings"), parameters.portfolio.holdings.map((h) => `${h.symbol} ${fmt.percent(h.weight, 0)}`).join(" · ")],
  ];
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="break-words tabular text-text">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function JobDetail({ id, onRemoved }: { id: string; onRemoved: () => void }) {
  const { t, fmt } = useI18n();
  const job = useJob(id);
  const cancel = useCancelJob();
  const remove = useDeleteJob();
  const [confirming, setConfirming] = useState(false);
  const data = job.data;

  if (job.isLoading) return <Skeleton className="h-[320px]" />;
  if (job.isError && problemKind(job.error) === "not-found") {
    return (
      <Card title={t("jobs.detail")}>
        <p className="text-[13px] text-text-2">{t("jobs.gone")}</p>
      </Card>
    );
  }
  if (job.isError || !data) return <ProblemAlert error={job.error} onRetry={() => void job.refetch()} />;

  const seconds = runSeconds(data);
  const failure = cancel.error ?? remove.error;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <Card
        title={t(`jobs.kind.${data.kind}` as MessageKey)}
        subtitle={fill(t("jobs.submitted"), { when: fmt.dateTime(data.created_at) })}
        actions={<Badge tone={statusTone(data.status)}>{t(STATUS[data.status])}</Badge>}
      >
        <div className="flex flex-col gap-4">
          {!isFinished(data.status) ? <ProgressBar job={data} /> : null}
          {data.cancel_requested && !isFinished(data.status) ? <p className="text-[13px] text-text-2">{t("jobs.cancelling")}</p> : null}
          {waitingForWorker(data) ? (
            <p role="status" className="flex items-start gap-2 text-[13px] leading-relaxed text-text-2">
              <Hourglass aria-hidden className="mt-0.5 size-4 shrink-0" />
              {t("jobs.noWorker")}
            </p>
          ) : null}
          {data.status === "failed" && data.error ? (
            <div role="alert" className="rounded-md border border-[color-mix(in_srgb,var(--critical)_35%,transparent)] p-3 text-[13px]">
              <p className="font-medium text-critical-text">{data.error.title}</p>
              <p className="mt-1 text-text-2">{data.error.detail}</p>
            </div>
          ) : null}
          <Parameters job={data} />
          <p className="text-xs text-muted tabular">
            {data.started_at ? fill(t("jobs.started"), { when: fmt.dateTime(data.started_at) }) : t("jobs.notStarted")}
            {seconds !== null ? ` · ${fill(t("jobs.took"), { seconds: fmt.number(seconds, 1) })}` : null}
            {data.attempts > 1 ? ` · ${fill(t("jobs.attempts"), { count: data.attempts })}` : null}
          </p>
          <div className="flex flex-wrap gap-2">
            {canCancel(data) ? (
              <Button size="sm" onClick={() => cancel.mutate(data.id)} disabled={cancel.isPending}>
                <Ban aria-hidden className="size-3.5" />
                {t("jobs.cancel")}
              </Button>
            ) : null}
            {canDelete(data) ? (
              confirming ? (
                <Button size="sm" variant="ghost" className="text-critical-text" onClick={() => remove.mutate(data.id, { onSuccess: onRemoved })} disabled={remove.isPending}>
                  {t("jobs.confirmDelete")}
                </Button>
              ) : (
                <Button size="sm" onClick={() => setConfirming(true)}>
                  <Trash2 aria-hidden className="size-3.5" />
                  {t("jobs.delete")}
                </Button>
              )
            ) : null}
          </div>
          {failure ? <ProblemAlert error={failure} /> : null}
        </div>
      </Card>
      {data.status === "succeeded" && data.result ? <SimulationResult data={data.result} currency={data.parameters.portfolio.base_currency ?? "EUR"} /> : null}
    </div>
  );
}

function JobsContent() {
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const jobs = useJobs();
  const selected = params.get("id");
  const select = (id: string | null) => router.replace(id === null ? pathname : `${pathname}?id=${id}`);

  if (jobs.isError && problemKind(jobs.error) === "persistence-not-configured") {
    return (
      <>
        <PageHeader title={t("jobs.title")} subtitle={t("jobs.subtitle")} />
        <Card title={t("jobs.list")}>
          <p className="text-[13px] leading-relaxed text-text-2">{t("jobs.off")}</p>
        </Card>
      </>
    );
  }
  return (
    <>
      <PageHeader title={t("jobs.title")} subtitle={t("jobs.subtitle")} />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <JobList selected={selected} onSelect={select} />
        {selected ? (
          <JobDetail key={selected} id={selected} onRemoved={() => select(null)} />
        ) : (
          <Card title={t("jobs.detail")}>
            <p className="text-[13px] text-text-2">{t("jobs.pick")}</p>
          </Card>
        )}
      </div>
    </>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[400px]" />}>
      <JobsContent />
    </Suspense>
  );
}
