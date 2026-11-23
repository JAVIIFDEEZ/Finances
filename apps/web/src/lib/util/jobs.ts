/**
 * Background jobs (ADR-0046): what the screens decide from a job, as pure functions. The
 * API says where a job is; these say how often to read it again, what can be done with it
 * and when a queued job waits for a worker that is not running.
 */

import type { Schemas } from "@/lib/api/client";

export type Job = Schemas["JobOut"];
export type SimulationJob = Schemas["SimulationJobOut"];
export type JobStatus = Job["status"];

/** Most paths of a simulation answered in the request; more run in the background. */
export const REQUEST_PATHS = 20_000;
/** Most paths of a simulation run in the background (the API's `max_job_paths`). */
export const JOB_PATHS = 200_000;
/** Milliseconds between two reads of a job that has not finished (the API's `Retry-After`). */
export const POLL_MS = 1_000;
/** Seconds a job may wait in the queue before the screen suggests starting a worker. */
export const QUEUE_PATIENCE_S = 10;

const FINISHED: ReadonlySet<JobStatus> = new Set(["succeeded", "failed", "cancelled"]);

/** Whether a job can no longer change. */
export function isFinished(status: JobStatus): boolean {
  return FINISHED.has(status);
}

/** How often to read again: every second while any job is unfinished, else never. */
export function refetchEvery(jobs: readonly Pick<Job, "status">[] | undefined): number | false {
  return jobs?.some((job) => !isFinished(job.status)) ? POLL_MS : false;
}

/** A job can be cancelled until it finishes, unless its cancellation is already on its way. */
export function canCancel(job: Pick<Job, "status" | "cancel_requested">): boolean {
  return !isFinished(job.status) && !job.cancel_requested;
}

/** Only a finished job can be deleted (the API answers `job-state` otherwise). */
export function canDelete(job: Pick<Job, "status">): boolean {
  return isFinished(job.status);
}

/** Colour of a job's status, by what it means for its owner. */
export function statusTone(status: JobStatus): "neutral" | "accent" | "good" | "warning" | "critical" {
  switch (status) {
    case "succeeded":
      return "good";
    case "failed":
      return "critical";
    case "cancelled":
      return "warning";
    case "running":
      return "accent";
    default:
      return "neutral";
  }
}

/** Seconds since an instant (never negative: clocks drift). */
export function secondsSince(instant: string, now: Date = new Date()): number {
  return Math.max(0, (now.getTime() - new Date(instant).getTime()) / 1_000);
}

/**
 * Whether a queued job waits for a worker that is not there.
 *
 * `workers` is how many the API saw alive (its readiness): with none, at once; with some, never
 * (the job waits its turn). When the API cannot tell, after waiting `QUEUE_PATIENCE_S`.
 */
export function waitingForWorker(
  job: Pick<Job, "status" | "created_at">,
  workers: number | null | undefined,
  now: Date = new Date(),
): boolean {
  if (job.status !== "queued") return false;
  if (workers !== null && workers !== undefined) return workers === 0;
  return secondsSince(job.created_at, now) >= QUEUE_PATIENCE_S;
}

/** Seconds a job ran, once it finished; `null` before (or if it never started). */
export function runSeconds(job: Pick<Job, "started_at" | "finished_at">): number | null {
  if (!job.started_at || !job.finished_at) return null;
  return Math.max(0, (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1_000);
}

/** Whether a simulation of `paths` only fits in the background. */
export function needsBackground(paths: number): boolean {
  return paths > REQUEST_PATHS;
}
