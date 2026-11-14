"use client";

/**
 * The price structure of an instrument (ADR-0036): support and resistance levels with their
 * touches, RSI/price divergences with the bar that confirmed them, and the Fibonacci levels of
 * the last swing. Every figure is the API's; nothing is rounded before it is shown.
 */

import { useI18n } from "@/components/providers";
import { Badge, Card, ProblemAlert, Refreshing, Skeleton } from "@/components/ui";
import type { useStructure } from "@/lib/api/queries";
import { fill } from "@/lib/i18n/messages";

import { SideMark } from "@/components/markets/technical";

type StructureQuery = ReturnType<typeof useStructure>;

export function StructureCard({ query, digits }: { query: StructureQuery; digits: number }) {
  const { t, fmt } = useI18n();
  const data = query.data;
  const price = (value: number | null | undefined) => fmt.number(value, digits);
  const nearest = new Set([data?.nearest_support, data?.nearest_resistance].filter((v) => v != null));
  return (
    <Card title={t("markets.structure")} subtitle={t("markets.structureNote")}>
      {query.isLoading ? (
        <Skeleton className="h-[260px]" />
      ) : query.isError ? (
        <ProblemAlert error={query.error} onRetry={() => void query.refetch()} />
      ) : data ? (
        <Refreshing active={query.isFetching}>
          <div className="flex flex-col gap-5">
            {data.basis === "close" ? <p className="text-xs text-muted">{t("markets.structureCloses")}</p> : null}
            <div className="grid grid-cols-1 items-start gap-x-8 gap-y-6 lg:grid-cols-2">
              {data.levels.length > 0 ? (
                <table className="w-full text-[13px]">
                  <caption className="mb-1 text-left text-xs font-medium text-text-2">
                    {t("markets.support")} / {t("markets.resistance")}
                  </caption>
                  <thead>
                    <tr className="text-xs text-muted">
                      <th scope="col" className="pb-1 text-left font-normal">
                        {t("markets.reading")}
                      </th>
                      <th scope="col" className="pb-1 text-right font-normal">
                        {t("markets.price")}
                      </th>
                      <th scope="col" className="pb-1 text-right font-normal">
                        {t("markets.touches")}
                      </th>
                      <th scope="col" className="pb-1 text-right font-normal">
                        {t("markets.distance")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.levels]
                      .sort((a, b) => b.price - a.price)
                      .map((level) => (
                        <tr key={level.price} className="border-t hairline">
                          <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                            <span className="inline-flex items-center gap-1.5 text-text-2">
                              <SideMark side={level.kind === "support" ? "up" : "down"} />
                              {t(level.kind === "support" ? "markets.support" : "markets.resistance")}
                              {nearest.has(level.price) ? (
                                <Badge tone="accent" icon={false}>
                                  {t("markets.nearest")}
                                </Badge>
                              ) : null}
                            </span>
                          </th>
                          <td className="tabular py-1.5 text-right text-text">{price(level.price)}</td>
                          <td className="tabular py-1.5 text-right text-text">{level.touches}</td>
                          <td className="tabular py-1.5 text-right text-muted">{fmt.signedPercent(level.distance_pct / 100, 2)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-text-2">{t("markets.noLevels")}</p>
              )}
              <div className="flex flex-col gap-5">
                <div className="flex flex-col gap-2">
                  <h3 className="text-xs font-medium text-text-2">{t("markets.divergences")}</h3>
                  {data.divergences.length > 0 ? (
                    <ul className="flex flex-col gap-2 text-[13px]">
                      {data.divergences.map((divergence) => (
                        <li key={`${divergence.kind}-${String(divergence.second_at)}`} className="flex flex-col gap-0.5">
                          <span className="inline-flex items-center gap-1.5 text-text">
                            <SideMark side={divergence.kind === "bullish" ? "up" : "down"} />
                            {t(`markets.divergence.${divergence.kind}`)}
                          </span>
                          <span className="pl-[18px] text-xs text-muted">
                            {price(divergence.price_first)} → {price(divergence.price_second)} · RSI {fmt.number(divergence.rsi_first, 1)} →{" "}
                            {fmt.number(divergence.rsi_second, 1)} · {fill(t("markets.confirmedOn"), { date: fmt.date(String(divergence.confirmed_at)) })}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted">{fill(t("markets.noDivergences"), { n: data.parameters.divergence_lookback ?? 80 })}</p>
                  )}
                </div>
                {data.fibonacci && data.fibonacci.levels.length > 0 ? (
                  <table className="w-full text-[13px]">
                    <caption className="mb-1 text-left text-xs font-medium text-text-2">{t("markets.fibonacci")}</caption>
                    <thead className="sr-only">
                      <tr>
                        <th scope="col">{t("markets.ratio")}</th>
                        <th scope="col">{t("markets.price")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.fibonacci.levels.map((level) => (
                        <tr key={level.ratio} className="border-t hairline">
                          <th scope="row" className="py-1 pr-2 text-left font-normal text-text-2">
                            <span className="inline-flex items-center gap-2">
                              {fmt.percent(level.ratio, 1)}
                              {data.fibonacci?.nearest === level.ratio ? (
                                <Badge tone="accent" icon={false}>
                                  {t("markets.nearest")}
                                </Badge>
                              ) : null}
                            </span>
                          </th>
                          <td className="tabular py-1 text-right text-text">{price(level.price)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={2} className="pt-2 text-xs text-muted">
                          {fill(t(data.fibonacci.rising ? "markets.swingUp" : "markets.swingDown"), {
                            low: price(data.fibonacci.low),
                            high: price(data.fibonacci.high),
                            lowAt: fmt.date(String(data.fibonacci.low_at)),
                            highAt: fmt.date(String(data.fibonacci.high_at)),
                          })}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                ) : null}
              </div>
            </div>
          </div>
        </Refreshing>
      ) : null}
    </Card>
  );
}
