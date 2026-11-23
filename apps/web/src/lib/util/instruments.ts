/**
 * What a symbol's notation says about the instrument (ADR-0032).
 *
 * A venue's spot pair is written ``BASE/QUOTE`` (``BTC/USDT``) and a perpetual swap
 * ``BASE/QUOTE:SETTLE`` (``BTC/USDT:USDT``); everything else is a Yahoo-style symbol.
 */

const PAIR = /^([A-Z0-9]{2,15})\/([A-Z0-9]{2,10})$/;

/** Quote of the pairs whose perpetual is inverse: the venues settle no swap in dollars. */
const INVERSE_QUOTE = "USD";

/**
 * The perpetual swap of a spot pair, or ``null``: the linear one settled in its quote asset
 * (``BTC/USDT`` → ``BTC/USDT:USDT``) or, for a pair in dollars, the inverse one settled in
 * its base asset (``BTC/USD`` → ``BTC/USD:BTC``).
 */
export function perpetualOf(symbol: string): string | null {
  const match = PAIR.exec(symbol);
  if (!match) return null;
  const [, base, quote] = match;
  return `${base}/${quote}:${quote === INVERSE_QUOTE ? base : quote}`;
}
