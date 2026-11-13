/**
 * What a symbol's notation says about the instrument (ADR-0032).
 *
 * A venue's spot pair is written ``BASE/QUOTE`` (``BTC/USDT``) and a perpetual swap
 * ``BASE/QUOTE:SETTLE`` (``BTC/USDT:USDT``); everything else is a Yahoo-style symbol.
 */

const PAIR = /^([A-Z0-9]{2,15})\/([A-Z0-9]{2,10})$/;

/** The linear perpetual swap of a spot pair (settled in its quote asset), or ``null``. */
export function perpetualOf(symbol: string): string | null {
  const match = PAIR.exec(symbol);
  if (!match) return null;
  const quote = match[2];
  return `${match[1]}/${quote}:${quote}`;
}
