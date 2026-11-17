"use client";

/**
 * The card of an instrument (ADR-0040): one tile per pillar of evidence its asset class has.
 * The technical pillar points somewhere and shows it on a meter; the others describe. A
 * pillar no source serves says so; those the asset class does not have are named below.
 */

import { SideMark } from "@/components/markets/technical";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Card, ProblemAlert, Refreshing, Skeleton } from "@/components/ui";
import { useCard } from "@/lib/api/queries";
import { isMessageKey } from "@/lib/i18n/messages";
import { factOf, factText, listedFacts, meterFill, scoreDirection, type Pillar } from "@/lib/util/card";

/** A score from -1 to +1 as a bar growing from the middle, with its figure beside it. */
function Meter({ score, label, hint }: { score: number | null | undefined; label: string; hint: string }) {
  const { fmt } = useI18n();
  const { tokens } = useTheme();
  const side = scoreDirection(score);
  const fill = meterFill(score);
  const text = score == null ? "—" : `${score > 0 ? "+" : ""}${fmt.number(score, 2)}`;
  return (
    <div className="flex items-center gap-3" title={hint}>
      <div role="meter" aria-label={label} aria-valuemin={-1} aria-valuemax={1} aria-valuenow={score ?? undefined} aria-valuetext={text} className="relative h-2 min-w-0 flex-1 rounded-full bg-surface-3">
        <span className="absolute inset-y-0 rounded-full" style={{ left: `${fill.left}%`, width: `${fill.width}%`, background: side === "up" ? tokens.up : side === "down" ? tokens.down : tokens.muted }} />
        {/* The middle of the scale: no direction. */}
        <span aria-hidden="true" className="absolute -inset-y-0.5 left-1/2 w-px bg-text-2" />
      </div>
      <span className="tabular inline-flex shrink-0 items-center gap-1.5 text-[15px] font-semibold text-text">
        <SideMark side={side} />
        {text}
      </span>
    </div>
  );
}

function PillarTile({ pillar }: { pillar: Pillar }) {
  const { t, fmt } = useI18n();
  const words = (key: string) => (isMessageKey(key) ? t(key) : null);
  const verdict = factOf(pillar, "verdict");
  const missing = `card.noData.${pillar.pillar}`;
  return (
    <section aria-label={t(`pillar.${pillar.pillar}`)} className="flex min-w-0 flex-col gap-3 rounded-lg border hairline bg-surface-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-text">{t(`pillar.${pillar.pillar}`)}</h3>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">{t(`pillar.${pillar.pillar}.note`)}</p>
        </div>
        {pillar.directional ? null : (
          <span title={t("card.describesHint")} className="shrink-0">
            <Badge icon={false}>{t("card.describes")}</Badge>
          </span>
        )}
      </div>
      {pillar.issue !== null ? (
        <p className="text-[13px] text-text-2">{isMessageKey(missing) ? t(missing) : t("card.noData")}</p>
      ) : (
        <>
          {pillar.directional ? (
            <div className="flex flex-col gap-1.5">
              {verdict ? <p className="text-[13px] font-medium text-text">{factText(verdict, fmt, words)}</p> : null}
              <Meter score={pillar.score} label={t("card.direction")} hint={t("card.directionHint")} />
            </div>
          ) : null}
          <dl className="flex flex-col text-[13px]">
            {listedFacts(pillar).map((fact) => {
              const label = `fact.${fact.key}`;
              return (
                <div key={fact.key} className="flex items-baseline justify-between gap-3 border-t hairline py-1.5 first:border-0 first:pt-0">
                  <dt className="min-w-0 text-text-2">{isMessageKey(label) ? t(label) : fact.key}</dt>
                  <dd className="tabular shrink-0 text-right font-medium text-text">{factText(fact, fmt, words)}</dd>
                </div>
              );
            })}
          </dl>
        </>
      )}
    </section>
  );
}

export function InstrumentCard({ symbol }: { symbol: string }) {
  const { t, fmt } = useI18n();
  const query = useCard(symbol);
  const data = query.data;
  return (
    <Card title={t("markets.card")} subtitle={data ? `${t("markets.cardNote")} · ${fmt.date(String(data.as_of))}` : t("markets.cardNote")}>
      {query.isLoading ? (
        <Skeleton className="h-[260px]" />
      ) : query.isError ? (
        <ProblemAlert error={query.error} onRetry={() => void query.refetch()} />
      ) : data ? (
        <Refreshing active={query.isFetching}>
          <div className="flex flex-col gap-3">
            {/* As many columns as fit tiles of a readable width: three or four on a desk, one on a phone. */}
            <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-[repeat(auto-fit,minmax(260px,1fr))]">
              {data.pillars.map((pillar) => (
                <PillarTile key={pillar.pillar} pillar={pillar} />
              ))}
            </div>
            {data.not_applicable.length > 0 ? (
              <p className="text-xs text-muted">
                {t("card.notApplicable")}: {data.not_applicable.map((pillar) => t(`pillar.${pillar}`)).join(", ")}
              </p>
            ) : null}
          </div>
        </Refreshing>
      ) : null}
    </Card>
  );
}
