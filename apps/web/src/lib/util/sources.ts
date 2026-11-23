/**
 * The data sources' heartbeat (ADR-0047): what the overview decides from what the worker last
 * saw of each source, as pure functions. The worker asks each source its canary every
 * quarter of an hour; a check much older than that means nobody is checking any more.
 */

import type { Schemas } from "@/lib/api/client";
import { secondsSince } from "@/lib/util/jobs";

export type SourceStatus = Schemas["SourceStatusOut"];
export type Provider = Schemas["ProviderOut"];

/** Minutes between two checks of the worker (the API's `SOURCES_CRON`). */
export const CHECK_EVERY_MIN = 15;
/** Minutes after which a check is too old to describe the source: three checks were missed. */
export const STALE_AFTER_MIN = 3 * CHECK_EVERY_MIN;

export type SourceState =
  /** A source of the owner's own (local files): it has no canary and is never checked. */
  | { kind: "local" }
  /** It has a canary, but the worker has not checked it yet. */
  | { kind: "unchecked" }
  /** It answered its last check, which is recent. */
  | { kind: "ok"; status: SourceStatus }
  /** It failed its last check, which is recent. */
  | { kind: "failing"; status: SourceStatus }
  /** Its last check is too old to say anything now: the worker stopped checking. */
  | { kind: "stale"; status: SourceStatus };

/** The state of a provider from its last status (if any), at `now`. */
export function sourceState(
  provider: Pick<Provider, "canary">,
  status: SourceStatus | undefined,
  now: Date = new Date(),
): SourceState {
  if (!status) return provider.canary ? { kind: "unchecked" } : { kind: "local" };
  if (secondsSince(status.checked_at, now) > STALE_AFTER_MIN * 60) return { kind: "stale", status };
  return status.ok ? { kind: "ok", status } : { kind: "failing", status };
}

/** The status of each source by name, to look one up from the list of providers. */
export function byProvider(statuses: readonly SourceStatus[] | undefined): ReadonlyMap<string, SourceStatus> {
  return new Map((statuses ?? []).map((status) => [status.provider, status]));
}

/** Colour of a source's state, by what it means for the data on screen. */
export function stateTone(state: SourceState): "neutral" | "good" | "warning" | "critical" {
  switch (state.kind) {
    case "ok":
      return "good";
    case "failing":
      return "critical";
    case "stale":
      return "warning";
    default:
      return "neutral";
  }
}

/** Seconds since the source last answered, while it fails; `null` if it never has. */
export function failingFor(status: Pick<SourceStatus, "ok" | "last_ok_at">, now: Date = new Date()): number | null {
  if (status.ok || !status.last_ok_at) return null;
  return secondsSince(status.last_ok_at, now);
}

/** Seconds since the latest observation a source answered; `null` without one. */
export function dataAge(status: Pick<SourceStatus, "latest_at">, now: Date = new Date()): number | null {
  return status.latest_at ? secondsSince(status.latest_at, now) : null;
}
