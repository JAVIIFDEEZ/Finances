/**
 * Typed client of the InvestingLab API, generated from apps/api/openapi.json.
 *
 * The browser calls this origin only: Next.js proxies `/api/v1/*` and `/health/*` to the
 * API (next.config.ts). Errors are RFC 9457 Problem Details, raised as {@link ApiError}.
 */

import createClient from "openapi-fetch";

import type { components, paths } from "@/lib/api/schema";

export type Schemas = components["schemas"];
export type Problem = Schemas["Problem"];

export const api = createClient<paths>({ baseUrl: "" });

/** A failed API call, with the Problem Details the server sent (when it sent any). */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null, message?: string) {
    super(message ?? problem?.detail ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }

  /** The request id the server quoted, to find the failure in its logs. */
  get requestId(): string | null {
    return this.problem?.instance?.replace("urn:request:", "") ?? null;
  }
}

function isProblem(value: unknown): value is Problem {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    "status" in value &&
    "detail" in value
  );
}

/** The data of an openapi-fetch result, or an {@link ApiError}. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined && result.response.ok) {
    return result.data;
  }
  const problem = isProblem(result.error) ? result.error : null;
  throw new ApiError(result.response.status, problem);
}

/** POST returning text (the Markdown report), with the same error handling. */
export async function postText(path: string, body: unknown, query: Record<string, string>): Promise<string> {
  const url = `${path}?${new URLSearchParams(query).toString()}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const problem: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, isProblem(problem) ? problem : null);
  }
  return response.text();
}
