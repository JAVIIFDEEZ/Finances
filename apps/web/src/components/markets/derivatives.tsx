"use client";

/**
 * What a perpetual swap of the pair says: its funding (ADR-0031), its positioning, the open
 * interest and how its traders stand (ADR-0042), and the depth of its book around the price
 * (ADR-0044). The venues offered come from the API (``/market/venues``): a venue added to
 * the platform appears here without touching this.
 */

import { useMemo, useState } from "react";

import { TimeSeriesChart, type TimeLine } from "@/components/charts/charts";
import { useI18n, useTheme } from "@/components/providers";
import { Card, ProblemAlert, Refreshing, Segmented, Skeleton, Stat } from "@/components/ui";
import { isNotFound, useBookDepth, useFunding, usePositioning, useVenues } from "@/lib/api/queries";
import { fill, isMessageKey } from "@/lib/i18n/messages";
import { seriesColor } from "@/lib/theme/tokens";
import { bandOf, bandPoints, chosenBand, liquidityOf, lastOf } from "@/lib/util/bookDepth";
import {
  CHARTED_RATIOS,
  chosenVenue,
  columnOf,
  columnPoints,
  fieldSlot,
  openInterestShown,
  POSITIONING_WINDOWS,
  positioningWindow,
  RATIO_FIELDS,
  relativeChange,
  venueLabel,
  type PositioningWindow,
} from "@/lib/util/positioning";

/** A picker of the venues the API offers; nothing while there is only one to choose. */
function VenuePicker({ label, offered, value, onChange }: { label: string; offered: readonly string[] | undefined; value: string | null; onChange: (venue: string) => void }) {
  if (!offered || offered.length < 2 || value === null) return null;
  return <Segmented label={label} value={value} onChange={onChange} options={offered.map((venue) => ({ value: venue, label: venueLabel(venue) }))} />;
}

/** Why a venue has nothing in these dates: what is known of it, or the general reason. */
function useNoneText(prefix: "markets.fundingNone" | "markets.positioningNone" | "markets.bookDepthNone"): (venue: string) => string {
  const { t } = useI18n();
  return (venue) => {
    const known = `${prefix}.${venue}`;
    return isMessageKey(known) ? t(known) : fill(t(prefix), { venue: venueLabel(venue) });
  };
}

export function FundingCard({ swap, start, color }: { swap: string; start: string | null; color: string }) {
  const { t, fmt } = useI18n();
  const venues = useVenues(swap, "holding_rates");
  const [picked, setPicked] = useState<string | null>(null);
  const venue = chosenVenue(venues.data?.venues, picked);
  const funding = useFunding(venue === null ? null : swap, start, venue);
  const none = useNoneText("markets.fundingNone");
  const percent = useMemo(() => (v: number) => fmt.percent(v, 1), [fmt]);
  const data = funding.data;
  const last = data?.rates[data.rates.length - 1]?.time;
  return (
    <Card
      title={t("markets.funding")}
      subtitle={swap}
      actions={<VenuePicker label={t("markets.fundingVenue")} offered={venues.data?.venues} value={venue} onChange={setPicked} />}
    >
      {venues.isLoading || funding.isLoading ? (
        <Skeleton className="h-[240px]" />
      ) : venues.isError ? (
        <ProblemAlert error={venues.error} onRetry={() => void venues.refetch()} />
      ) : venue === null ? (
        <p className="text-[13px] text-text-2">{t("markets.fundingNoVenue")}</p>
      ) : funding.isError && isNotFound(funding.error) ? (
        <p className="text-[13px] text-text-2">{none(venue)}</p>
      ) : funding.isError ? (
        <ProblemAlert error={funding.error} onRetry={() => void funding.refetch()} />
      ) : data ? (
        <div className="flex flex-col gap-4">
          <Refreshing active={funding.isFetching}>
            <TimeSeriesChart
              height={180}
              label={t("markets.fundingRate")}
              format={percent}
              reference={0}
              lines={[{ name: t("markets.fundingRate"), color, points: data.rates.map((r) => ({ time: String(r.time), value: r.annualized })) }]}
            />
          </Refreshing>
          <p className="text-xs text-muted">
            {t("metric.fundingPayer")}
            {last ? ` · ${fill(t("markets.fundingLast"), { date: fmt.date(String(last)) })}` : null}
            {/* About the data shown: while another venue loads, the previous one stays, dimmed. */}
            {data.venue === "binance" ? ` · ${t("markets.fundingMonthly")}` : null}
          </p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
            <Stat label={t("metric.fundingMean")} value={fmt.percent(data.summary.mean_annualized, 1)} />
            <Stat label={t("metric.fundingLong")} value={fmt.signedPercent(data.summary.accumulated_long, 2)} />
            <Stat label={t("metric.fundingPositive")} value={fmt.percent(data.summary.positive_share, 0)} />
            <Stat label={t("metric.fundingInterval")} value={`${fmt.number(data.interval_hours, 0)} h`} detail={`${fmt.number(data.summary.payments, 0)} ${t("metric.observations").toLowerCase()}`} />
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

export function PositioningCard({ swap }: { swap: string }) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const venues = useVenues(swap, "positioning");
  const [picked, setPicked] = useState<string | null>(null);
  const [span, setSpan] = useState<PositioningWindow>("30d");
  const venue = chosenVenue(venues.data?.venues, picked);
  // The window's first day is fixed while the card is open: one request per choice.
  const { start, interval } = useMemo(() => positioningWindow(span), [span]);
  const positioning = usePositioning(swap, venue, interval, start);
  const none = useNoneText("markets.positioningNone");
  const compact = useMemo(() => (v: number) => fmt.compact(v), [fmt]);
  const ratio = useMemo(() => (v: number) => fmt.number(v, 2), [fmt]);
  const data = positioning.data;
  const shown = data ? openInterestShown(data) : null;
  const unit = shown ? (shown.currency ?? (swap.split("/")[0] ?? "")) : "";
  const ratios = useMemo<TimeLine[]>(
    () =>
      data
        ? CHARTED_RATIOS.flatMap((field) => {
            const column = columnOf(data, field);
            return column ? [{ name: t(`positioning.short.${field}`), color: seriesColor(tokens, fieldSlot(field)), points: columnPoints(data, column) }] : [];
          })
        : [],
    [data, t, tokens],
  );
  return (
    <Card
      title={t("markets.positioning")}
      subtitle={data ? `${swap} · ${venueLabel(data.venue)}` : swap}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label={t("markets.positioningWindow")} value={span} onChange={setSpan} options={POSITIONING_WINDOWS.map((value) => ({ value, label: value.replace("d", " d") }))} />
          <VenuePicker label={t("markets.positioningVenue")} offered={venues.data?.venues} value={venue} onChange={setPicked} />
        </div>
      }
    >
      {venues.isLoading || positioning.isLoading ? (
        <Skeleton className="h-[320px]" />
      ) : venues.isError ? (
        <ProblemAlert error={venues.error} onRetry={() => void venues.refetch()} />
      ) : venue === null ? (
        <p className="text-[13px] text-text-2">{t("markets.positioningNoVenue")}</p>
      ) : positioning.isError && isNotFound(positioning.error) ? (
        <p className="text-[13px] text-text-2">{none(venue)}</p>
      ) : positioning.isError ? (
        <ProblemAlert error={positioning.error} onRetry={() => void positioning.refetch()} />
      ) : data ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            {shown ? (
              <Refreshing active={positioning.isFetching}>
                <TimeSeriesChart
                  height={200}
                  label={fill(t("markets.openInterestIn"), { unit })}
                  format={compact}
                  lines={[{ name: t("positioning.open_interest"), color: seriesColor(tokens, fieldSlot(shown.column.field)), area: true, points: columnPoints(data, shown.column) }]}
                />
              </Refreshing>
            ) : null}
            {ratios.length > 0 ? (
              <Refreshing active={positioning.isFetching}>
                <TimeSeriesChart height={200} label={t("markets.longShortRatios")} format={ratio} reference={1} lines={ratios} />
              </Refreshing>
            ) : null}
            <p className="text-xs text-muted">{t("markets.positioningNote")}</p>
          </div>
          <dl className="grid grid-cols-2 content-start gap-x-6 gap-y-5 lg:grid-cols-1">
            {shown ? (
              <Stat
                label={t("positioning.open_interest")}
                value={`${fmt.compact(shown.column.latest)} ${unit}`}
                detail={`${t("markets.positioningChange")}: ${fmt.signedPercent(relativeChange(shown.column), 1)}`}
              />
            ) : null}
            {RATIO_FIELDS.map((field) => {
              const column = columnOf(data, field);
              return column ? (
                <Stat key={field} label={t(`positioning.${field}`)} value={fmt.number(column.latest, 2)} detail={`${fmt.number(column.minimum, 2)} – ${fmt.number(column.maximum, 2)}`} />
              ) : null;
            })}
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

export function BookDepthCard({ swap }: { swap: string }) {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const venues = useVenues(swap, "book_depth");
  const [picked, setPicked] = useState<string | null>(null);
  const [span, setSpan] = useState<PositioningWindow>("7d");
  const [pickedBand, setPickedBand] = useState<number | null>(null);
  const venue = chosenVenue(venues.data?.venues, picked);
  const { start, interval } = useMemo(() => positioningWindow(span), [span]);
  const book = useBookDepth(swap, venue, interval, start);
  const none = useNoneText("markets.bookDepthNone");
  const compact = useMemo(() => (v: number) => fmt.compact(v), [fmt]);
  const ratio = useMemo(() => (v: number) => fmt.number(v, 2), [fmt]);
  const data = book.data;
  const bands = data?.bands.map((item) => item.band) ?? [];
  const band = chosenBand(bands, pickedBand);
  const current = data && band !== null ? bandOf(data, band) : undefined;
  const liquidity = data && current ? liquidityOf(data, current) : null;
  const unit = liquidity ? (liquidity.unit ?? (swap.split("/")[0] ?? "")) : "";
  const bandText = (value: number) => `±${fmt.number(value, value < 1 ? 1 : 0)} %`;
  return (
    <Card
      title={t("markets.bookDepth")}
      subtitle={data ? `${swap} · ${venueLabel(data.venue)}` : swap}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label={t("markets.bookDepthWindow")} value={span} onChange={setSpan} options={POSITIONING_WINDOWS.map((value) => ({ value, label: value.replace("d", " d") }))} />
          {bands.length > 1 && band !== null ? (
            <Segmented
              label={t("markets.bookDepthBand")}
              value={String(band)}
              onChange={(value) => setPickedBand(Number(value))}
              options={bands.map((value) => ({ value: String(value), label: bandText(value) }))}
            />
          ) : null}
          <VenuePicker label={t("markets.bookDepthVenue")} offered={venues.data?.venues} value={venue} onChange={setPicked} />
        </div>
      }
    >
      {venues.isLoading || book.isLoading ? (
        <Skeleton className="h-[320px]" />
      ) : venues.isError ? (
        <ProblemAlert error={venues.error} onRetry={() => void venues.refetch()} />
      ) : venue === null ? (
        <p className="text-[13px] text-text-2">{t("markets.bookDepthNoVenue")}</p>
      ) : book.isError && isNotFound(book.error) ? (
        <p className="text-[13px] text-text-2">{none(venue)}</p>
      ) : book.isError ? (
        <ProblemAlert error={book.error} onRetry={() => void book.refetch()} />
      ) : data && current && liquidity && band !== null ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <p className="text-xs font-medium text-text-2">{fill(t(liquidity.valued ? "markets.bookLiquidityIn" : "markets.bookQuantityIn"), { band: bandText(band), unit })}</p>
            <Refreshing active={book.isFetching}>
              <TimeSeriesChart
                height={200}
                label={fill(t(liquidity.valued ? "markets.bookLiquidityIn" : "markets.bookQuantityIn"), { band: bandText(band), unit })}
                format={compact}
                lines={[{ name: t("markets.bookLiquidity"), color: seriesColor(tokens, 0), area: true, points: bandPoints(data, liquidity.values) }]}
              />
            </Refreshing>
            <p className="text-xs font-medium text-text-2">{fill(t("markets.bookImbalanceIn"), { band: bandText(band) })}</p>
            <Refreshing active={book.isFetching}>
              <TimeSeriesChart
                height={180}
                label={fill(t("markets.bookImbalanceIn"), { band: bandText(band) })}
                format={ratio}
                reference={0}
                lines={[{ name: t("markets.bookImbalance"), color: seriesColor(tokens, 1), points: bandPoints(data, current.imbalance) }]}
              />
            </Refreshing>
            <p className="text-xs text-muted">{t("markets.bookDepthNote")}</p>
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
              <Stat label={fill(t("markets.bookLiquidityLabel"), { band: bandText(band) })} value={`${fmt.compact(lastOf(liquidity.values))} ${unit}`} />
              <Stat label={t("markets.bookImbalance")} value={fmt.number(current.latest_imbalance, 2)} detail={t("markets.bookImbalanceHint")} />
            </dl>
            <table className="w-full text-[13px]">
              <caption className="sr-only">{t("markets.bookTable")}</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="py-1 font-medium">{t("markets.bookBand")}</th>
                  <th scope="col" className="py-1 text-right font-medium">{t("markets.bookBids")}</th>
                  <th scope="col" className="py-1 text-right font-medium">{t("markets.bookAsks")}</th>
                  <th scope="col" className="py-1 text-right font-medium">{t("markets.bookImbalanceShort")}</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {data.bands.map((item) => (
                  <tr key={item.band} className={`border-t hairline ${item.band === band ? "text-text" : "text-text-2"}`}>
                    <th scope="row" className="py-1.5 text-left font-medium">{bandText(item.band)}</th>
                    <td className="py-1.5 text-right">{fmt.compact(item.latest_bid)}</td>
                    <td className="py-1.5 text-right">{fmt.compact(item.latest_ask)}</td>
                    <td className="py-1.5 text-right">{fmt.number(item.latest_imbalance, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-muted">{fill(t("markets.bookTableNote"), { unit: swap.split("/")[0] ?? "" })}</p>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
