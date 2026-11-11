import { describe, expect, it } from "vitest";

import { ApiError, unwrap } from "@/lib/api/client";

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
