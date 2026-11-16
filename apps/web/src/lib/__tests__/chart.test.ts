import { describe, expect, it } from "vitest";

import { barChange, extent, linearTicks, logTicks, paneLayout, spacedTicks, spread, spreadLabels, tickKind, tickUnit, trough, unitStart } from "@/lib/util/chart";

/** Weekdays from ``start`` (ISO date), as a market calendar without holidays would give. */
function sessions(start: string, count: number): string[] {
  const out: string[] = [];
  const day = new Date(`${start}T12:00:00Z`);
  while (out.length < count) {
    if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) out.push(day.toISOString().slice(0, 10));
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return out;
}

describe("paneLayout", () => {
  it("stacks the panes with a gap and keeps room under the last", () => {
    const layout = paneLayout(
      [
        { id: "price", height: 300 },
        { id: "volume", height: 60 },
      ],
      { top: 8, gap: 10, foot: 50 },
    );
    expect(layout.panes).toEqual([
      { id: "price", height: 300, top: 8 },
      { id: "volume", height: 60, top: 318 },
    ]);
    expect(layout.height).toBe(8 + 300 + 10 + 60 + 50);
  });

  it("is only the margins without panes", () => {
    expect(paneLayout([], { top: 8, foot: 20 })).toEqual({ panes: [], height: 28 });
  });
});

describe("unitStart", () => {
  it("tells the first bar of a week, a month, a quarter and a year", () => {
    expect(unitStart("2026-11-13", "2026-11-16", "week")).toBe(true); // Friday to Monday
    expect(unitStart("2026-11-16", "2026-11-17", "week")).toBe(false);
    expect(unitStart("2026-10-30", "2026-11-02", "month")).toBe(true);
    expect(unitStart("2026-10-30", "2026-11-02", "quarter")).toBe(false);
    expect(unitStart("2026-09-30", "2026-10-01", "quarter")).toBe(true);
    expect(unitStart("2025-12-31", "2026-01-02", "year")).toBe(true);
  });

  it("reads intraday bars by the date they carry", () => {
    expect(unitStart("2026-11-13T17:00:00+01:00", "2026-11-16T09:00:00+01:00", "day")).toBe(true);
    expect(unitStart("2026-11-16T09:00:00+01:00", "2026-11-16T10:00:00+01:00", "day")).toBe(false);
  });

  it("a week missing its Monday still starts on its first session", () => {
    expect(unitStart("2026-04-02", "2026-04-07", "week")).toBe(true); // Easter Monday closed
  });
});

describe("tickUnit", () => {
  const year = sessions("2025-11-17", 260);

  it("marks days on a few bars, months on a year and years on a decade", () => {
    expect(tickUnit(year, 240, 259, 8)).toBe("week");
    expect(tickUnit(year, 252, 259, 8)).toBe("day");
    expect(tickUnit(year, 0, 259, 14)).toBe("month");
    expect(tickUnit(year, 0, 259, 6)).toBe("quarter");
    expect(tickUnit(sessions("2016-01-04", 2600), 0, 2599, 8)).toBe("year");
  });

  it("falls back to years when even those are too many", () => {
    expect(tickUnit(sessions("2000-01-03", 6000), 0, 5999, 3)).toBe("year");
  });
});

describe("tickKind", () => {
  it("names the year at its first bar, the month at its first, else the day", () => {
    expect(tickKind("2025-12-31", "2026-01-02", "month")).toBe("year");
    expect(tickKind("2026-01-30", "2026-02-02", "month")).toBe("month");
    expect(tickKind("2026-01-30", "2026-02-02", "week")).toBe("month");
    expect(tickKind("2026-02-06", "2026-02-09", "week")).toBe("day");
    expect(tickKind("2026-02-06", "2026-02-09", "year")).toBe("year");
  });
});

describe("linearTicks", () => {
  it("gives round values inside the range", () => {
    expect(linearTicks(31.2, 48.7, 5)).toEqual([35, 40, 45]);
    expect(linearTicks(0.8612, 0.8791, 4)).toEqual([0.865, 0.87, 0.875]);
    expect(linearTicks(5, 5)).toEqual([]);
  });
});

describe("logTicks", () => {
  it("uses 1-2-5 values across decades", () => {
    expect(logTicks(800, 110_000, 7)).toEqual([1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000]);
  });

  it("uses evenly stepped values on a narrow range", () => {
    expect(logTicks(31.2, 48.7, 4)).toEqual([35, 40, 45]);
  });

  it("stays inside the range and needs positive prices", () => {
    for (const tick of logTicks(3.4, 912, 5)) expect(tick >= 3.4 && tick <= 912).toBe(true);
    expect(logTicks(0, 10)).toEqual([]);
    expect(logTicks(10, 10)).toEqual([]);
  });
});

describe("barChange", () => {
  it("compares a close with the one before", () => {
    expect(barChange([100, 104], 1)).toEqual({ absolute: 4, relative: 0.040000000000000036 });
    expect(barChange([100, 104], 0)).toBeNull();
    expect(barChange([0, 5], 1)).toBeNull();
  });
});

describe("spread", () => {
  it("subtracts bar by bar and keeps the gaps", () => {
    const line = new Map<string, number | null>([
      ["a", 1],
      ["b", null],
      ["c", 3],
      ["d", 4],
    ]);
    const signal = new Map<string, number | null>([
      ["a", 0.5],
      ["b", 1],
      ["c", null],
    ]);
    expect([...spread(line, signal)]).toEqual([
      ["a", 0.5],
      ["b", null],
      ["c", null],
      ["d", null],
    ]);
  });
});

describe("trough", () => {
  it("finds the lowest defined point", () => {
    expect(trough([{ time: "a", value: -0.1 }, { time: "b", value: null }, { time: "c", value: -0.4 }, { time: "d", value: -0.2 }])).toEqual({ time: "c", value: -0.4 });
    expect(trough([{ value: null }])).toBeNull();
  });
});

describe("extent", () => {
  it("ignores what is missing", () => {
    expect(extent([3, null, -1, undefined, Number.NaN, 7])).toEqual([-1, 7]);
    expect(extent([null])).toBeNull();
  });
});

describe("spacedTicks", () => {
  it("drops a tick too close to the one above it", () => {
    expect(spacedTicks([20, 25], 60, 100)).toEqual([25]); // 5 of 60 over 100 px: 8 px apart
    expect(spacedTicks([30, 70], 100, 100)).toEqual([30, 70]);
  });
});

describe("spreadLabels", () => {
  it("leaves alone the labels that already fit", () => {
    expect(spreadLabels([10, 40, 80], 12)).toEqual([0, 0, 0]);
  });

  it("spreads two that meet around their middle, in any order", () => {
    expect(spreadLabels([100, 102], 12)).toEqual([-5, 5]);
    expect(spreadLabels([102, 100], 12)).toEqual([5, -5]);
  });

  it("packs a chain of three and keeps them a gap apart", () => {
    const positions = [50, 54, 58, 200];
    const placed = spreadLabels(positions, 12).map((move, i) => (positions[i] ?? 0) + move);
    expect(placed).toEqual([42, 54, 66, 200]);
  });
});
