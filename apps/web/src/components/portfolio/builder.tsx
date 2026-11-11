"use client";

import { Plus, RotateCcw, Scale, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useI18n } from "@/components/providers";
import { Badge, Button, Card, Field, Input, Select } from "@/components/ui";
import {
  DEFAULT_PORTFOLIO,
  portfolioSchema,
  usePortfolio,
  type PortfolioDraft,
  type RebalanceChoice,
} from "@/lib/portfolio/store";

const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "JPY"] as const;

/** Edit the portfolio: weights in percent with live validation; "Analyse" commits it. */
export function PortfolioBuilder() {
  const committed = usePortfolio((state) => state.draft);
  // Re-mount with the stored portfolio when it changes (restored after mount, or weights
  // applied from the optimiser), instead of syncing state in an effect.
  return <BuilderForm key={JSON.stringify(committed)} initial={committed} />;
}

function BuilderForm({ initial }: { initial: PortfolioDraft }) {
  const { t, fmt } = useI18n();
  const setDraft = usePortfolio((state) => state.setDraft);
  const [draft, setLocal] = useState<PortfolioDraft>(initial);

  const validation = useMemo(() => portfolioSchema.safeParse(draft), [draft]);
  const total = draft.holdings.reduce((sum, h) => sum + (Number.isFinite(h.weight) ? h.weight : 0), 0);
  const update = (changes: Partial<PortfolioDraft>) => setLocal((current) => ({ ...current, ...changes }));
  const setHolding = (index: number, changes: Partial<PortfolioDraft["holdings"][number]>) =>
    update({ holdings: draft.holdings.map((h, i) => (i === index ? { ...h, ...changes } : h)) });

  const equalWeights = () => {
    const n = draft.holdings.length;
    if (n === 0) return;
    const base = Math.floor((10_000 / n)) / 100;
    update({ holdings: draft.holdings.map((h, i) => ({ ...h, weight: i === 0 ? Math.round((100 - base * (n - 1)) * 100) / 100 : base })) });
  };
  const normalize = () => {
    if (total === 0) return;
    update({ holdings: draft.holdings.map((h) => ({ ...h, weight: (h.weight / total) * 100 })) });
  };

  return (
    <Card title={t("portfolio.builder")} subtitle={t("portfolio.editHint")}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (validation.success) setDraft({ ...draft, holdings: draft.holdings.map((h) => ({ ...h, symbol: h.symbol.trim().toUpperCase() })) });
        }}
      >
        <Field label={t("portfolio.name")} htmlFor="portfolio-name">
          <Input id="portfolio-name" value={draft.name} onChange={(e) => update({ name: e.target.value })} maxLength={80} />
        </Field>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-xs font-medium text-text-2">{t("portfolio.holdings")}</legend>
          {draft.holdings.map((holding, index) => (
            <div key={index} className="grid grid-cols-[minmax(0,1fr)_88px_32px] items-center gap-2">
              <Input
                aria-label={`${t("common.symbol")} ${index + 1}`}
                placeholder={t("portfolio.symbolPlaceholder")}
                value={holding.symbol}
                onChange={(e) => setHolding(index, { symbol: e.target.value })}
                className="font-mono uppercase"
                spellCheck={false}
                autoCapitalize="characters"
              />
              <div className="relative">
                <Input
                  aria-label={`${t("common.weight")} ${holding.symbol || index + 1}`}
                  type="number"
                  step="0.5"
                  min={draft.allowShort ? -100 : 0}
                  max={200}
                  value={Number.isFinite(holding.weight) ? Math.round(holding.weight * 100) / 100 : ""}
                  onChange={(e) => setHolding(index, { weight: e.target.value === "" ? Number.NaN : Number(e.target.value) })}
                  className="pr-6 text-right tabular"
                />
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted">%</span>
              </div>
              <button
                type="button"
                aria-label={`${t("portfolio.remove")} ${holding.symbol}`}
                onClick={() => update({ holdings: draft.holdings.filter((_, i) => i !== index) })}
                className="grid size-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-critical-text"
              >
                <Trash2 aria-hidden className="size-4" />
              </button>
              <input
                type="range"
                aria-hidden
                tabIndex={-1}
                min={0}
                max={100}
                step={0.5}
                value={Math.max(0, Math.min(100, holding.weight || 0))}
                onChange={(e) => setHolding(index, { weight: Number(e.target.value) })}
                className="col-span-2 h-1 accent-[var(--accent)]"
              />
            </div>
          ))}
          <div className="mt-1 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => update({ holdings: [...draft.holdings, { symbol: "", weight: 0 }] })} disabled={draft.holdings.length >= 25}>
              <Plus aria-hidden className="size-3.5" /> {t("portfolio.addHolding")}
            </Button>
            <Button size="sm" variant="ghost" onClick={equalWeights}>
              <Scale aria-hidden className="size-3.5" /> {t("portfolio.equalWeight")}
            </Button>
            <Button size="sm" variant="ghost" onClick={normalize}>
              {t("portfolio.normalize")}
            </Button>
          </div>
        </fieldset>

        <div className="flex items-center justify-between gap-3 rounded-md bg-surface-2 px-3 py-2">
          <span className="text-xs text-text-2">{t("portfolio.total")}</span>
          <span className="flex items-center gap-2">
            <span className="tabular text-[13px] font-semibold text-text">{fmt.percent(total / 100, 1)}</span>
            {validation.success ? (
              <Badge tone="good">{t("portfolio.valid")}</Badge>
            ) : (
              <Badge tone="critical">{t("portfolio.invalid")}</Badge>
            )}
          </span>
        </div>
        {!validation.success ? (
          <ul className="-mt-2 list-disc pl-5 text-xs text-critical-text">
            {validation.error.issues.map((issue) => (
              <li key={issue.message}>{issue.message}</li>
            ))}
          </ul>
        ) : null}

        <div className="grid grid-cols-2 gap-3">
          <Field label={t("portfolio.baseCurrency")} htmlFor="portfolio-currency">
            <Select id="portfolio-currency" value={draft.baseCurrency ?? ""} onChange={(e) => update({ baseCurrency: e.target.value || null })}>
              <option value="">{t("portfolio.baseCurrencyAuto")}</option>
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("common.start")} htmlFor="portfolio-start">
            <Input id="portfolio-start" type="date" value={draft.start} max={new Date().toISOString().slice(0, 10)} onChange={(e) => update({ start: e.target.value })} />
          </Field>
        </div>
        <Field label={t("portfolio.rebalance")} htmlFor="portfolio-rebalance">
          <Select id="portfolio-rebalance" value={draft.rebalance} onChange={(e) => update({ rebalance: e.target.value as RebalanceChoice })}>
            <option value="periodic">{t("portfolio.rebalance.periodic")}</option>
            <option value="quarterly">{t("portfolio.rebalance.quarterly")}</option>
            <option value="threshold">{t("portfolio.rebalance.threshold")}</option>
            <option value="buy_and_hold">{t("portfolio.rebalance.buyAndHold")}</option>
          </Select>
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-text-2">
          <input type="checkbox" checked={draft.allowShort} onChange={(e) => update({ allowShort: e.target.checked })} className="size-4 accent-[var(--accent)]" />
          {t("portfolio.allowShort")}
        </label>

        <div className="flex gap-2">
          <Button type="submit" variant="primary" className="flex-1" disabled={!validation.success}>
            {t("portfolio.analyze")}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setLocal(DEFAULT_PORTFOLIO)} aria-label={t("portfolio.reset")} title={t("portfolio.reset")}>
            <RotateCcw aria-hidden className="size-4" />
          </Button>
        </div>
      </form>
    </Card>
  );
}

/** The committed portfolio in one line, with a link to edit it (analysis screens). */
export function PortfolioSummary() {
  const { t, fmt } = useI18n();
  const draft = usePortfolio((state) => state.draft);
  return (
    <div className="flex flex-col gap-2 rounded-lg border hairline bg-surface px-4 py-3 md:flex-row md:items-center md:justify-between">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
        <span className="font-semibold text-text">{draft.name}</span>
        {draft.holdings.map((h) => (
          <span key={h.symbol} className="font-mono text-text-2">
            {h.symbol} <span className="text-muted">{fmt.percent(h.weight / 100, 0)}</span>
          </span>
        ))}
        <span className="text-xs text-muted">
          {draft.baseCurrency ?? "—"} · {t("common.start")} {fmt.date(draft.start)}
        </span>
      </div>
      <Link href="/portfolio" className="text-xs font-medium text-accent hover:underline">
        {t("portfolio.editPortfolio")}
      </Link>
    </div>
  );
}
