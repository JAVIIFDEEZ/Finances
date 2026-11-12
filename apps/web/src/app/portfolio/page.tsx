"use client";

import { Download } from "lucide-react";
import { useMemo, useState } from "react";

import { CorrelationHeatmap, GroupedBars, TimeSeriesChart } from "@/components/charts/charts";
import { PortfolioBuilder } from "@/components/portfolio/builder";
import { SavedPortfolios } from "@/components/portfolio/saved";
import { useI18n, useTheme } from "@/components/providers";
import { Badge, Button, Card, PageHeader, ProblemAlert, Refreshing, Skeleton, Stat, StatGrid } from "@/components/ui";
import { postText } from "@/lib/api/client";
import { useAnalytics } from "@/lib/api/queries";
import { toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";
import { seriesColor } from "@/lib/theme/tokens";
import type { Locale } from "@/lib/i18n/messages";

function ReportButtons() {
  const { t } = useI18n();
  const draft = usePortfolio((state) => state.draft);
  const [busy, setBusy] = useState<Locale | null>(null);
  const [failed, setFailed] = useState<unknown>(null);
  const download = async (language: Locale) => {
    setBusy(language);
    setFailed(null);
    try {
      const text = await postText("/api/v1/portfolios/report", toPortfolioIn(draft), { language });
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${draft.name.trim().replace(/[^\p{L}\p{N}]+/gu, "-") || "portfolio"}-${language}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setFailed(error);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => void download("es")} disabled={busy !== null}>
          <Download aria-hidden className="size-3.5" /> {busy === "es" ? "…" : t("portfolio.reportEs")}
        </Button>
        <Button size="sm" onClick={() => void download("en")} disabled={busy !== null}>
          <Download aria-hidden className="size-3.5" /> {busy === "en" ? "…" : t("portfolio.reportEn")}
        </Button>
      </div>
      {failed ? <ProblemAlert error={failed} /> : null}
    </div>
  );
}

const REBALANCE_LABELS = {
  periodic: "portfolio.rebalance.periodic",
  quarterly: "portfolio.rebalance.quarterly",
  threshold: "portfolio.rebalance.threshold",
  buy_and_hold: "portfolio.rebalance.buyAndHold",
} as const;

function Analysis() {
  const { t, fmt } = useI18n();
  const { tokens } = useTheme();
  const draft = usePortfolio((state) => state.draft);
  const request = useMemo(() => toPortfolioIn(draft), [draft]);
  const analytics = useAnalytics(request);
  const data = analytics.data;
  const percent = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);
  const level = useMemo(() => (v: number) => fmt.number(v, 0), [fmt]);
  const share = useMemo(() => (v: number) => fmt.percent(v, 0), [fmt]);

  if (analytics.isError && !data) {
    return <ProblemAlert error={analytics.error} onRetry={() => void analytics.refetch()} />;
  }
  if (!data) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-[120px]" />
        <Skeleton className="h-[360px]" />
        <Skeleton className="h-[300px]" />
      </div>
    );
  }
  const metrics = data.metrics;
  const var95 = metrics.tail.find((r) => r.level === 0.95 && r.method === "historical");
  const color = seriesColor(tokens, 0);
  return (
    <Refreshing active={analytics.isFetching}>
      <div className="flex flex-col gap-6">
        {analytics.isError ? <ProblemAlert error={analytics.error} onRetry={() => void analytics.refetch()} /> : null}
        <Card
          title={`${t("portfolio.analysisOf")} ${data.name}`}
          subtitle={`${fmt.date(String(data.start))} – ${fmt.date(String(data.end))} · ${data.base_currency} · ${t(REBALANCE_LABELS[draft.rebalance])}`}
          actions={<Badge tone={metrics.risk_free_coverage === 1 ? "good" : "warning"}>{`${t("metric.riskFreeCoverage")}: ${fmt.percent(metrics.risk_free_coverage, 0)}`}</Badge>}
        >
          <StatGrid>
            <Stat label={t("metric.cagr")} value={fmt.percent(metrics.annualized_return)} detail={`${t("metric.totalReturn")} ${fmt.signedPercent(metrics.total_return, 0)}`} />
            <Stat label={t("metric.volatility")} value={fmt.percent(metrics.annualized_volatility)} />
            <Stat
              label={t("metric.sharpe")}
              value={fmt.number(metrics.sharpe_ratio, 2)}
              detail={metrics.sharpe_standard_error != null ? `± ${fmt.number(metrics.sharpe_standard_error, 2)} ${t("metric.sharpeError")}` : undefined}
            />
            <Stat label={t("metric.sortino")} value={fmt.number(metrics.sortino_ratio, 2)} detail={`${t("metric.calmar")} ${fmt.number(metrics.calmar_ratio, 2)}`} />
            <Stat label={t("metric.maxDrawdown")} value={fmt.percent(metrics.max_drawdown)} />
            <Stat label={t("metric.var95")} value={fmt.percent(var95?.value_at_risk ?? null, 2)} detail={`CVaR ${fmt.percent(var95?.conditional_value_at_risk ?? null, 2)}`} />
          </StatGrid>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t hairline pt-4">
            <span className="text-xs text-text-2">{t("portfolio.report")}</span>
            <ReportButtons />
          </div>
        </Card>

        <Card title={t("portfolio.value")}>
          <TimeSeriesChart height={300} reference={100} label={t("portfolio.value")} format={level} lines={[{ name: data.name, color, area: true, points: data.value.map((p) => ({ time: String(p.time), value: p.value })) }]} />
        </Card>
        <Card title={t("markets.drawdown")}>
          <TimeSeriesChart height={200} label={t("markets.drawdown")} format={percent} lines={[{ name: data.name, color, area: true, points: data.drawdown.map((p) => ({ time: String(p.time), value: p.value })) }]} />
        </Card>

        <div className="grid gap-6 xl:grid-cols-2">
          <Card title={t("portfolio.contributions")} subtitle={`${t("portfolio.effectiveAssets")}: ${fmt.number(data.effective_number_of_assets, 1)}`}>
            <GroupedBars
              label={t("portfolio.contributions")}
              format={share}
              categories={data.risk_contributions.map((c) => c.symbol)}
              series={[
                { name: t("common.weight"), color: seriesColor(tokens, 0), values: data.risk_contributions.map((c) => c.weight) },
                { name: t("portfolio.riskShare"), color: seriesColor(tokens, 1), values: data.risk_contributions.map((c) => c.share ?? 0) },
              ]}
            />
          </Card>
          <Card title={t("markets.correlation")}>
            <CorrelationHeatmap labels={data.correlation.labels} values={data.correlation.values} label={t("markets.correlation")} />
          </Card>
        </div>

        <div className="grid gap-6 2xl:grid-cols-2">
          <Card title={t("portfolio.episodes")} padded={false}>
            <div className="overflow-x-auto">
            <table className="w-full whitespace-nowrap text-[13px]">
              <thead className="text-left text-xs text-text-2">
                <tr className="border-b hairline">
                  <th className="px-4 py-2.5 font-medium">{t("portfolio.peak")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("portfolio.trough")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("portfolio.recovery")}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{t("portfolio.depth")}</th>
                </tr>
              </thead>
              <tbody>
                {data.drawdown_episodes.map((episode) => (
                  <tr key={String(episode.peak)} className="border-b hairline last:border-0">
                    <td className="px-4 py-2.5">{fmt.date(String(episode.peak))}</td>
                    <td className="px-4 py-2.5">{fmt.date(String(episode.trough))}</td>
                    <td className="px-4 py-2.5 text-text-2">{episode.recovery ? fmt.date(String(episode.recovery)) : <Badge tone="warning">{t("portfolio.notRecovered")}</Badge>}</td>
                    <td className="px-4 py-2.5 text-right font-medium text-critical-text">{fmt.percent(episode.depth)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </Card>
          <Card title={t("portfolio.holdings")} padded={false}>
            <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="text-left text-xs text-text-2">
                <tr className="border-b hairline">
                  <th className="px-4 py-2.5 font-medium">{t("common.symbol")}</th>
                  <th className="px-4 py-2.5 font-medium">{t("common.name")}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{t("common.weight")}</th>
                  <th className="px-4 py-2.5 text-right font-medium">{t("portfolio.riskShare")}</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings.map((holding) => {
                  const contribution = data.risk_contributions.find((c) => c.symbol === holding.symbol);
                  return (
                    <tr key={holding.symbol} className="border-b hairline last:border-0">
                      <td className="px-4 py-2.5 font-mono">{holding.symbol}</td>
                      <td className="max-w-[220px] truncate px-4 py-2.5 text-text-2">{holding.name}</td>
                      <td className="px-4 py-2.5 text-right">{fmt.percent(holding.weight, 1)}</td>
                      <td className="px-4 py-2.5 text-right">{fmt.percent(contribution?.share ?? null, 1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </Card>
        </div>
      </div>
    </Refreshing>
  );
}

export default function PortfolioPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("portfolio.title")} subtitle={t("portfolio.subtitle")} />
      <div className="grid items-start gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <PortfolioBuilder />
          <SavedPortfolios />
        </div>
        <Analysis />
      </div>
    </>
  );
}
