import { describe, expect, it } from "vitest";

import {
  STALE_AFTER_MIN,
  byProvider,
  dataAge,
  failingFor,
  sourceState,
  stateTone,
  type SourceStatus,
} from "@/lib/util/sources";

const NOW = new Date("2026-11-23T12:00:00Z");
const CANARY = { canary: { dataset: "bars", symbol: "^GSPC" } } as const;

function status(changes: Partial<SourceStatus> = {}): SourceStatus {
  return {
    provider: "yahoo",
    checked_at: "2026-11-23T11:45:00Z",
    ok: true,
    latency_seconds: 0.42,
    latest_at: "2026-11-20T00:00:00Z",
    error: null,
    last_ok_at: "2026-11-23T11:45:00Z",
    failures: 0,
    ...changes,
  };
}

describe("sourceState", () => {
  it("tells a source of one's own from one not checked yet", () => {
    expect(sourceState({ canary: null }, undefined, NOW)).toEqual({ kind: "local" });
    expect(sourceState(CANARY, undefined, NOW)).toEqual({ kind: "unchecked" });
  });

  it("reads a recent check as it is", () => {
    const failed = status({ ok: false, latest_at: null, error: "TimeoutError", failures: 2 });

    expect(sourceState(CANARY, status(), NOW).kind).toBe("ok");
    expect(sourceState(CANARY, failed, NOW).kind).toBe("failing");
  });

  it("says nothing of now from a check three intervals old", () => {
    const edge = new Date(NOW.getTime() - STALE_AFTER_MIN * 60_000).toISOString();
    const older = new Date(NOW.getTime() - (STALE_AFTER_MIN * 60 + 1) * 1_000).toISOString();

    expect(sourceState(CANARY, status({ checked_at: edge }), NOW).kind).toBe("ok");
    expect(sourceState(CANARY, status({ checked_at: older }), NOW).kind).toBe("stale");
  });
});

describe("what a status says", () => {
  it("colours each state by what it means", () => {
    expect(stateTone({ kind: "ok", status: status() })).toBe("good");
    expect(stateTone({ kind: "failing", status: status() })).toBe("critical");
    expect(stateTone({ kind: "stale", status: status() })).toBe("warning");
    expect(stateTone({ kind: "unchecked" })).toBe("neutral");
    expect(stateTone({ kind: "local" })).toBe("neutral");
  });

  it("counts how long a source has failed, and how old its data is", () => {
    expect(failingFor(status({ ok: false, last_ok_at: "2026-11-23T11:00:00Z" }), NOW)).toBe(3_600);
    expect(failingFor(status({ ok: false, last_ok_at: null }), NOW)).toBeNull(); // never answered
    expect(failingFor(status(), NOW)).toBeNull();
    expect(dataAge(status(), NOW)).toBe(3.5 * 86_400);
    expect(dataAge(status({ latest_at: null }), NOW)).toBeNull();
  });

  it("finds each source's status by name", () => {
    const statuses = [status(), status({ provider: "ecb" })];

    expect(byProvider(statuses).get("ecb")?.provider).toBe("ecb");
    expect(byProvider(undefined).size).toBe(0);
  });
});
