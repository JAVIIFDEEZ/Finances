"use client";

/**
 * The confluence of an instrument across timeframes (ADR-0038): on each frame, eleven
 * conventional rules and the background trend; together, whether the frames agree. The rules
 * that follow a move and those that fade it are counted apart, because they read a trend the
 * opposite way. Everything here describes; nothing is advice.
 */

import { useState } from "react";

import { SideMark } from "@/components/markets/technical";
import { useI18n, useTheme } from "@/components/providers";
import { Button, Card, ProblemAlert, Refreshing, Segmented, Skeleton } from "@/components/ui";
import { useConfluence } from "@/lib/api/queries";
import { fill, isMessageKey } from "@/lib/i18n/messages";
import { biasSide, byStyle, firstReadable, PRESETS, ruleFigure, scoreSide, signed, type Frame, type FrameCode, type Preset } from "@/lib/util/confluence";
import { groupUnavailable } from "@/lib/util/technical";

/** A text of the interface by a key built at run time (the key itself if the web lacks it). */
function useLabel(): (prefix: string, code: string) => string {
  const { t } = useI18n();
  return (prefix, code) => {
    const key = `${prefix}.${code}`;
    return isMessageKey(key) ? t(key) : code;
  };
}

/** The rules of a frame as a bar: up, neutral and down, in the order of the counts beside it. */
function RulesBar({ frame }: { frame: Frame }) {
  const { tokens } = useTheme();
  const parts = [
    { count: frame.bullish, color: tokens.up, opacity: 1 },
    { count: frame.neutral, color: tokens.muted, opacity: 0.45 },
    { count: frame.bearish, color: tokens.down, opacity: 1 },
  ].filter((part) => part.count > 0);
  return (
    <div aria-hidden="true" className="flex h-2 w-full max-w-[200px] gap-0.5">
      {parts.map((part) => (
        <span key={part.color} className="h-full rounded-[2px]" style={{ flexGrow: part.count, background: part.color, opacity: part.opacity }} />
      ))}
    </div>
  );
}

function Counts({ frame }: { frame: Frame }) {
  const { t } = useI18n();
  return (
    <p className="mt-1 text-xs text-text-2">
      <span aria-hidden="true" className="tabular inline-flex items-center gap-1.5">
        {frame.bullish}
        <SideMark side="up" />
        {frame.neutral}
        <SideMark side="flat" />
        {frame.bearish}
        <SideMark side="down" />
      </span>
      <span className="sr-only">{fill(t("confluence.count"), { up: frame.bullish, flat: frame.neutral, down: frame.bearish })}</span>
    </p>
  );
}

export function ConfluenceCard({ symbol, digits }: { symbol: string; digits: number }) {
  const { t, fmt, locale } = useI18n();
  const label = useLabel();
  const [preset, setPreset] = useState<Preset>("positional");
  const [picked, setPicked] = useState<FrameCode | null>(null);
  const query = useConfluence(symbol, PRESETS[preset]);
  const data = query.data;
  const shown = data?.frames.find((frame) => frame.frequency === picked && frame.issue === null) ?? (data ? firstReadable(data.frames) : undefined);
  const agreeing = data?.agreement != null ? Math.round(data.agreement * data.frames_read) : 0;
  const explain = !data
    ? ""
    : data.verdict === "mixed"
      ? fill(t("confluence.explain.mixed"), { agree: agreeing, n: data.frames_read })
      : data.verdict === "neutral"
        ? t("confluence.explain.neutral")
        : data.verdict === "insufficient"
          ? t("confluence.explain.insufficient")
          : fill(t("confluence.explain.aligned"), { agree: agreeing, n: data.frames_read });
  return (
    <Card
      title={t("markets.confluence")}
      subtitle={t("markets.confluenceNote")}
      actions={
        <Segmented
          label={t("confluence.preset")}
          value={preset}
          options={(Object.keys(PRESETS) as Preset[]).map((value) => ({ value, label: t(`confluence.preset.${value}`) }))}
          onChange={(value) => {
            setPreset(value);
            setPicked(null);
          }}
        />
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-[280px]" />
      ) : query.isError ? (
        <ProblemAlert error={query.error} onRetry={() => void query.refetch()} />
      ) : data ? (
        <Refreshing active={query.isFetching}>
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-3 rounded-lg border hairline bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-base font-semibold tracking-tight text-text">
                  <SideMark side={data.verdict === "aligned_bullish" ? "up" : data.verdict === "aligned_bearish" ? "down" : "flat"} />
                  {t(`confluence.verdict.${data.verdict}`)}
                </p>
                <p className="mt-1 max-w-2xl text-xs text-muted">{explain}</p>
              </div>
              <dl className="shrink-0 sm:text-right">
                <dt className="text-xs text-muted" title={t("confluence.alignmentHint")}>
                  {t("confluence.alignment")}
                </dt>
                <dd className="tabular text-lg font-semibold text-text">
                  {/* One frame is not an alignment: nothing to show until two can be read. */}
                  {data.verdict === "insufficient" ? "—" : signed(fmt.number(data.alignment, 2), data.alignment)}
                </dd>
              </dl>
            </div>

            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-xs text-muted">
                  <th scope="col" className="pb-1 text-left font-normal">
                    {t("confluence.frame")}
                  </th>
                  <th scope="col" className="pb-1 text-left font-normal">
                    {t("confluence.trend")}
                  </th>
                  <th scope="col" className="pb-1 text-left font-normal">
                    {t("confluence.rules")}
                  </th>
                  <th scope="col" className="pb-1 text-right font-normal">
                    {t("confluence.net")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.frames.map((frame) => (
                  <tr key={frame.frequency} className="border-t hairline align-top">
                    <th scope="row" className="py-2 pr-2 text-left font-normal">
                      {frame.issue === null ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-pressed={shown?.frequency === frame.frequency}
                          aria-label={`${label("frame", frame.frequency)}: ${t("confluence.show")}`}
                          onClick={() => setPicked(frame.frequency)}
                          className="h-auto min-h-7 justify-start border hairline px-2 text-left text-[13px] font-normal aria-pressed:bg-accent-wash aria-pressed:text-text"
                        >
                          {label("frame", frame.frequency)}
                        </Button>
                      ) : (
                        <span className="inline-flex min-h-7 items-center px-2 text-text-2">{label("frame", frame.frequency)}</span>
                      )}
                      <span className="mt-0.5 block px-2 text-[11px] text-muted">{fill(t("confluence.weight"), { w: fmt.number(frame.weight, 0) })}</span>
                    </th>
                    {frame.issue !== null ? (
                      <td colSpan={3} className="py-2 pt-3 text-xs text-muted">
                        {frame.issue === "no_data" ? t("confluence.issue.no_data") : fill(t("confluence.issue.too_few_bars"), { bars: frame.bars, needed: data.min_bars })}
                      </td>
                    ) : (
                      <>
                        <td className="py-2 pr-2">
                          {frame.trend ? (
                            <>
                              <span className="inline-flex items-center gap-1.5 text-text">
                                <SideMark side={frame.trend.direction === "up" ? "up" : frame.trend.direction === "down" ? "down" : "flat"} />
                                {t(`trend.${frame.trend.direction}`)}
                              </span>
                              <span className="mt-0.5 block text-[11px] text-muted">
                                {fill(t("confluence.vsAverage"), { pct: fmt.signedPercent(frame.trend.price_vs_sma_pct / 100, 1), n: frame.trend.sma_window })}
                              </span>
                            </>
                          ) : (
                            <span className="text-muted">—</span>
                          )}
                        </td>
                        <td className="py-2 pr-2 pt-3">
                          <RulesBar frame={frame} />
                          <Counts frame={frame} />
                        </td>
                        <td className="py-2 text-right">
                          <span className="tabular inline-flex items-center gap-1.5 font-semibold text-text">
                            <SideMark side={scoreSide(frame.score)} />
                            {signed(fmt.number(frame.score, 2), frame.score)}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-muted">{frame.verdict ? t(`panel.${frame.verdict}`) : "—"}</span>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>

            {shown ? (
              <div className="flex flex-col gap-3 border-t hairline pt-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <h3 className="text-xs font-medium text-text-2">{fill(t("confluence.rulesOf"), { frame: label("frame", shown.frequency).toLowerCase() })}</h3>
                  <p className="text-xs text-muted">
                    {shown.last_at ? fill(t("confluence.until"), { date: fmt.date(String(shown.last_at)) }) : null}
                    {shown.derived ? ` · ${t("confluence.derived")}` : null}
                  </p>
                </div>
                <div className="grid grid-cols-1 items-start gap-x-8 gap-y-5 lg:grid-cols-2">
                  {byStyle(shown.rules).map((group) => {
                    const net = group.style === "trend" ? shown.trend_score : shown.reversal_score;
                    return (
                      <table key={group.style} className="w-full text-[13px]">
                        <caption className="mb-1 text-left text-xs font-medium text-text-2">
                          {t(`confluence.style.${group.style}`)}
                          <span className="tabular ml-2 font-normal text-muted">
                            {t("confluence.net")} {signed(fmt.number(net, 2), net)}
                          </span>
                        </caption>
                        <thead className="sr-only">
                          <tr>
                            <th scope="col">{t("confluence.rules")}</th>
                            <th scope="col">{t("markets.value")}</th>
                            <th scope="col">{t("markets.reading")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.rules.map((rule) => (
                            <tr key={rule.name} className="border-t hairline">
                              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-text">
                                {label("rule", rule.name)}
                                <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-2 sm:hidden">
                                  <SideMark side={biasSide(rule.bias)} />
                                  {t(`direction.${rule.bias}`)}
                                </span>
                              </th>
                              <td className="tabular py-1.5 text-right align-top whitespace-nowrap text-text sm:align-middle">{ruleFigure(rule, fmt.number, digits)}</td>
                              <td className="hidden w-24 py-1.5 pl-4 text-xs text-text-2 sm:table-cell">
                                <span className="inline-flex items-center gap-1.5">
                                  <SideMark side={biasSide(rule.bias)} />
                                  {t(`direction.${rule.bias}`)}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    );
                  })}
                </div>
                <p className="max-w-3xl text-xs text-muted">{t("confluence.styleNote")}</p>
                {groupUnavailable(shown.skipped).map((group) => (
                  <p key={group.missing.join()} className="text-xs text-muted">
                    {group.missing.includes("undefined")
                      ? t("confluence.undefined")
                      : `${t("markets.needs")} ${new Intl.ListFormat(locale, { type: "conjunction" }).format(group.missing.map((column) => label("column", column)))}`}
                    : {group.names.map((name) => label("rule", name)).join(", ")}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        </Refreshing>
      ) : null}
    </Card>
  );
}
