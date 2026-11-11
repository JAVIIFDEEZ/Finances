import { describe, expect, it } from "vitest";

import { rangeStart, thin } from "@/lib/util/dates";

describe("date ranges", () => {
  const today = new Date(2026, 10, 10); // 10 November 2026

  it("computes the start of each preset", () => {
    expect(rangeStart("1m", today)).toBe("2026-10-10");
    expect(rangeStart("ytd", today)).toBe("2026-01-01");
    expect(rangeStart("1y", today)).toBe("2025-11-10");
    expect(rangeStart("5y", today)).toBe("2021-11-10");
    expect(rangeStart("max", today)).toBeNull();
  });

  it("thins long series but always keeps the latest value", () => {
    const values = Array.from({ length: 1000 }, (_, i) => i);
    const kept = thin(values, 50);
    expect(kept.length).toBeLessThanOrEqual(52);
    expect(kept[0]).toBe(0);
    expect(kept[kept.length - 1]).toBe(999);
    expect(thin([1, 2, 3], 50)).toEqual([1, 2, 3]);
  });
});
