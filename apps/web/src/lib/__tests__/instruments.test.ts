import { describe, expect, it } from "vitest";

import { perpetualOf } from "@/lib/util/instruments";

describe("perpetualOf", () => {
  it("names the linear swap of a spot pair", () => {
    expect(perpetualOf("BTC/USDT")).toBe("BTC/USDT:USDT");
    expect(perpetualOf("1000SATS/USDC")).toBe("1000SATS/USDC:USDC");
  });

  it("has nothing for symbols that are not pairs", () => {
    for (const symbol of ["SAN.MC", "^GSPC", "EURUSD=X", "BTC-USD", "BTC/USDT:USDT", "btc/usdt"]) {
      expect(perpetualOf(symbol)).toBeNull();
    }
  });
});
