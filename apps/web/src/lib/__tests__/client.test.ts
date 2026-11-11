import { describe, expect, it } from "vitest";

import { ApiError, failureOf, unwrap } from "@/lib/api/client";

const problem = {
  type: "https://example.test/api.md#data-not-found",
  title: "Data not found",
  status: 404,
  detail: "Data unavailable for 'NOPE.XX'",
  instance: "urn:request:abc123",
};

describe("unwrap", () => {
  it("returns the data of a successful call", () => {
    expect(unwrap({ data: { ok: true }, response: new Response(null, { status: 200 }) })).toEqual({ ok: true });
  });

  it("raises the Problem Details of a failed call, with its request id", () => {
    let caught: unknown;
    try {
      unwrap({ error: problem, response: new Response(null, { status: 404 }) });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError.status).toBe(404);
    expect(apiError.message).toBe(problem.detail);
    expect(apiError.requestId).toBe("abc123");
  });

  it("copes with failures that are not Problem Details (a proxy error page)", () => {
    expect(() => unwrap({ error: "<html>", response: new Response(null, { status: 502 }) })).toThrow("HTTP 502");
  });
});

describe("failureOf", () => {
  const answered = (status: number) => new ApiError(status, { ...problem, status });

  it("blames the API when it did not answer: down, unreachable or another program on its port", () => {
    expect(failureOf(new TypeError("Failed to fetch"))).toBe("api");
    expect(failureOf(new ApiError(500, null))).toBe("api"); // the proxy could not reach it
    expect(failureOf(new ApiError(404, null))).toBe("api"); // someone else answered
    expect(failureOf(new ApiError(405, null))).toBe("api");
  });

  it("reads what the API answered", () => {
    expect(failureOf(answered(404))).toBe("notFound");
    expect(failureOf(answered(422))).toBe("invalid");
    expect(failureOf(answered(503))).toBe("sources"); // every provider failed
    expect(failureOf(answered(504))).toBe("sources");
  });
});
