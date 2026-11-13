/**
 * Bands of the crypto Fear & Greed Index, as alternative.me publishes them (0 = extreme fear,
 * 100 = extreme greed).
 */

export type FearGreedBand = "extremeFear" | "fear" | "neutral" | "greed" | "extremeGreed";

const UPPER_BOUNDS: readonly [number, FearGreedBand][] = [
  [25, "extremeFear"],
  [46, "fear"],
  [54, "neutral"],
  [75, "greed"],
  [100, "extremeGreed"],
];

/** The band of a reading, or ``null`` outside 0-100 or when there is no reading. */
export function fearGreedBand(value: number | null | undefined): FearGreedBand | null {
  if (value == null || !Number.isFinite(value) || value < 0 || value > 100) return null;
  for (const [upper, band] of UPPER_BOUNDS) {
    if (value <= upper) return band;
  }
  return null;
}

/** Whether a band is one of the two extremes (shown as a warning). */
export function isExtreme(band: FearGreedBand | null): boolean {
  return band === "extremeFear" || band === "extremeGreed";
}
