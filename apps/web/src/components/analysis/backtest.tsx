"use client";

import { useMemo } from "react";

import { TimeSeriesChart } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Card, Stat, StatGrid } from "@/components/ui";
import { fill, isMessageKey, type MessageKey } from "@/lib/i18n/messages";
import { seriesColor } from "@/lib/theme/tokens";
import { costLines, costShare, excessReturn, type Backtest } from "@/lib/util/backtest";

/** Trades listed at most: the latest ones (the counts and the statistics cover them all). */
const TRADES_SHOWN = 50;

/**
 * What a backtest did (ADR-0050, ADR-0051): its figures against holding, its equity, what it
 * cost and why, the market's profile with what it assumes and leaves out, and its trades.
 * The same view for a backtest answered in the request and for one run in the background.
 */
export function BacktestResult({ data }: { data: Backtest }) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const money = useMemo(() => (v: number) => fmt.money(v, data.currency), [fmt, data.currency]);
  const excess = excessReturn(data);
  const share = costShare(data);
  const lines = costLines(data.costs);
  const market = data.market;
  const profile = market?.profile;
  const trades = data.trades.slice(-TRADES_SHOWN).reverse();
  const reason = (key: string) => (isMessageKey(`backtest.reason.${key}`) ? t(`backtest.reason.${key}` as MessageKey) : key);
  const period = fill(t("backtest.period"), { start: fmt.date(data.start), end: fmt.date(data.end) });
  const ready = data.ready_at ? ` · ${fill(t("backtest.ready"), { date: fmt.date(data.ready_at) })}` : "";

  return (
    <div className="flex flex-col gap-6">
      <Card title={t("backtest.summary")} subtitle={`${data.symbol} · ${period}${ready}`}>
        <StatGrid>
          <Stat label={t("backtest.return")} value={fmt.percent(data.total_return, 1)} delta={`${fmt.percent(excess, 1)} ${t("backtest.excess").toLowerCase()}`} deltaGood={excess >= 0} />
          <Stat label={t("backtest.buyAndHold")} value={fmt.percent(data.buy_and_hold, 1)} />
          <Stat label={t("backtest.sharpe")} value={fmt.number(data.metrics.sharpe_ratio ?? null, 2)} />
          <Stat label={t("backtest.drawdown")} value={fmt.percent(data.metrics.max_drawdown ?? null, 1)} />
          <Stat label={t("backtest.trades")} value={fmt.number(data.statistics.count, 0)} detail={`${t("backtest.winRate")} ${fmt.percent(data.statistics.win_rate ?? null, 0)}`} />
          <Stat label={t("backtest.exposure")} value={fmt.percent(data.exposure, 0)} />
        </StatGrid>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Card title={t("backtest.equity")}>
          <TimeSeriesChart
            label={t("backtest.equity")}
            format={money}
            reference={data.initial_capital}
            lines={[{ name: data.symbol, color: seriesColor(tokens, 0), points: data.equity }]}
          />
        </Card>
        <Card title={t("backtest.equity")} padded={false}>
          <dl className="divide-y hairline text-[13px]">
            {(
              [
                [t("backtest.initial"), money(data.initial_capital)],
                [t("backtest.final"), money(data.final_equity)],
                [t("backtest.return"), fmt.percent(data.total_return, 2)],
                [t("backtest.buyAndHold"), fmt.percent(data.buy_and_hold, 2)],
                [t("backtest.drawdown"), fmt.percent(data.metrics.max_drawdown ?? null, 2)],
                [t("backtest.profitFactor"), fmt.number(data.statistics.profit_factor ?? null, 2)],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 px-4 py-2.5">
                <dt className="text-text-2">{label}</dt>
                <dd className="tabular text-text">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title={t("backtest.costs")} subtitle={share === null ? undefined : fill(t("backtest.costShare"), { share: fmt.percent(share, 2) })} padded={false}>
          {lines.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-text-2">{t("backtest.noCosts")}</p>
          ) : (
            <dl className="divide-y hairline text-[13px]">
              {lines.map((line) => (
                <div key={line.kind} className="flex items-baseline justify-between gap-4 px-4 py-2.5">
                  <dt className="text-text-2">{t(`backtest.cost.${line.kind}` as MessageKey)}</dt>
                  <dd className="tabular text-text">{money(line.value)}</dd>
                </div>
              ))}
              <div className="flex items-baseline justify-between gap-4 px-4 py-2.5 font-medium">
                <dt className="text-text">{t("backtest.cost.total")}</dt>
                <dd className="tabular text-text">{money(data.costs.total)}</dd>
              </div>
            </dl>
          )}
        </Card>

        {market && profile ? (
          <Card title={t("backtest.market")} subtitle={`${profile.name} · ${fill(t("backtest.asOf"), { date: fmt.date(profile.as_of) })}`}>
            <div className="flex flex-col gap-3 text-[13px] leading-relaxed">
              <div className="flex flex-wrap gap-2">
                <Badge tone="neutral" icon={false}>
                  {profile.key}
                </Badge>
                <Badge tone="neutral" icon={false}>
                  {fill(t("backtest.bps"), { value: fmt.number(market.commission_bps, 1) })}
                </Badge>
              </div>
              <p className="text-text-2">
                {profile.tax === null
                  ? t("backtest.noTax")
                  : market.tax_presumed
                    ? fill(t("backtest.taxPresumed"), { tax: profile.tax })
                    : fill(t(market.taxable ? "backtest.taxPaid" : "backtest.taxNotPaid"), { tax: profile.tax })}
              </p>
              {profile.assumed.length > 0 ? (
                <p className="text-text-2">
                  <span className="font-medium text-text">{t("backtest.assumed")}: </span>
                  {profile.assumed.map((field) => (isMessageKey(`backtest.assumed.${field}`) ? t(`backtest.assumed.${field}` as MessageKey) : field)).join(", ")}
                </p>
              ) : null}
              {profile.unmodelled.length > 0 ? (
                <div className="text-text-2">
                  <p className="font-medium text-text">{t("backtest.unmodelled")}</p>
                  <ul className="mt-1 list-disc pl-5">
                    {profile.unmodelled.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {profile.sources.length > 0 ? (
                <p className="break-words text-xs text-muted">
                  {t("backtest.sources")}:{" "}
                  {profile.sources.map((source, index) => (
                    <a key={source} href={source} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                      {`[${index + 1}]`}
                    </a>
                  ))}
                </p>
              ) : null}
            </div>
          </Card>
        ) : null}
      </div>

      <Card
        title={t("backtest.trades")}
        subtitle={data.trades.length > TRADES_SHOWN ? fill(t("backtest.lastTrades"), { shown: TRADES_SHOWN, count: data.trades.length }) : undefined}
        padded={false}
      >
        {trades.length === 0 ? (
          <p className="px-4 py-3 text-[13px] text-text-2">{t("backtest.noTrades")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead className="text-left text-xs text-text-2">
                <tr className="border-b hairline">
                  <th className="px-4 py-2.5 font-medium">{t("backtest.side")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("backtest.entry")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("backtest.exit")}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{t("backtest.tradeReturn")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("backtest.reason")}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{t("backtest.bars")}</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade) => (
                  <tr key={`${trade.entry_time}-${trade.exit_time}`} className="border-b hairline last:border-0">
                    <td className="px-4 py-2.5 text-text">{t(`backtest.side.${trade.side}` as MessageKey)}</td>
                    <td className="px-4 py-2.5 tabular text-text-2">{fmt.date(trade.entry_time)}</td>
                    <td className="px-4 py-2.5 tabular text-text-2">{fmt.date(trade.exit_time)}</td>
                    <td className={`px-4 py-2.5 text-right tabular ${trade.pnl >= 0 ? "text-good-text" : "text-critical-text"}`}>{fmt.percent(trade.trade_return, 2)}</td>
                    <td className="px-4 py-2.5 text-text-2">{reason(trade.exit_reason)}</td>
                    <td className="px-4 py-2.5 text-right tabular text-text-2">{fmt.number(trade.bars, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
