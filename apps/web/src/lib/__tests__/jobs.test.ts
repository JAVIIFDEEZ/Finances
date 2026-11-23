import { describe, expect, it } from "vitest";

import {
  POLL_MS,
  canCancel,
  canDelete,
  isFinished,
  needsBackground,
  refetchEvery,
  runSeconds,
  secondsSince,
  statusTone,
  waitingForWorker,
} from "@/lib/util/jobs";

const NOW = new Date("2026-11-23T12:00:30Z");

describe("isFinished", () => {
  it("is true for the three last states only", () => {
    expect(["queued", "running"].map((s) => isFinished(s as never))).toEqual([false, false]);
    expect(["succeeded", "failed", "cancelled"].map((s) => isFinished(s as never))).toEqual([true, true, true]);
  });
});

describe("refetchEvery", () => {
  it("polls while any job has not finished, and stops after", () => {
    expect(refetchEvery([{ status: "succeeded" }, { status: "running" }])).toBe(POLL_MS);
    expect(refetchEvery([{ status: "succeeded" }, { status: "failed" }])).toBe(false);
    expect(refetchEvery([])).toBe(false);
    expect(refetchEvery(undefined)).toBe(false);
  });
});

describe("what can be done with a job", () => {
  it("cancels until it finishes, once", () => {
    expect(canCancel({ status: "queued", cancel_requested: false })).toBe(true);
    expect(canCancel({ status: "running", cancel_requested: true })).toBe(false);
    expect(canCancel({ status: "succeeded", cancel_requested: false })).toBe(false);
  });

  it("deletes only what has finished", () => {
    expect(canDelete({ status: "running" })).toBe(false);
    expect(canDelete({ status: "cancelled" })).toBe(true);
  });
});

describe("statusTone", () => {
  it("colours each state by what it means", () => {
    expect(["queued", "running", "succeeded", "failed", "cancelled"].map((s) => statusTone(s as never))).toEqual([
      "neutral",
      "accent",
      "good",
      "critical",
      "warning",
    ]);
  });
});

describe("timing", () => {
  it("counts seconds, never negative", () => {
    expect(secondsSince("2026-11-23T12:00:00Z", NOW)).toBe(30);
    expect(secondsSince("2026-11-23T12:01:00Z", NOW)).toBe(0);
  });

  it("suspects a missing worker only for a job queued a while", () => {
    expect(waitingForWorker({ status: "queued", created_at: "2026-11-23T12:00:00Z" }, NOW)).toBe(true);
    expect(waitingForWorker({ status: "queued", created_at: "2026-11-23T12:00:25Z" }, NOW)).toBe(false);
    expect(waitingForWorker({ status: "running", created_at: "2026-11-23T11:00:00Z" }, NOW)).toBe(false);
  });

  it("measures the run once finished", () => {
    expect(runSeconds({ started_at: "2026-11-23T12:00:00Z", finished_at: "2026-11-23T12:00:04.5Z" })).toBe(4.5);
    expect(runSeconds({ started_at: "2026-11-23T12:00:00Z", finished_at: null })).toBeNull();
    expect(runSeconds({ started_at: null, finished_at: "2026-11-23T12:00:00Z" })).toBeNull();
  });
});

describe("needsBackground", () => {
  it("sends past the request limit to the background", () => {
    expect(needsBackground(20_000)).toBe(false);
    expect(needsBackground(20_001)).toBe(true);
  });
});
