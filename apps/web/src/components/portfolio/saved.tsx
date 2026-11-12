"use client";

import { FolderOpen, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "@/components/providers";
import { Badge, Button, Card, ProblemAlert, Skeleton } from "@/components/ui";
import { problemKind, useDeleteSavedPortfolio, useSavedPortfolios, useSavePortfolio } from "@/lib/api/queries";
import type { MessageKey } from "@/lib/i18n/messages";
import { portfolioSchema, toPortfolioIn, usePortfolio } from "@/lib/portfolio/store";

/** What to tell the user when a save or a delete is refused, by kind of problem. */
const REFUSALS: Record<string, MessageKey> = {
  "name-conflict": "saved.nameTaken",
  "version-conflict": "saved.conflict",
  "not-found": "saved.gone",
};

/** Save the analysed portfolio and open or delete the ones saved before. */
export function SavedPortfolios() {
  const { t, fmt } = useI18n();
  const draft = usePortfolio((state) => state.draft);
  const current = usePortfolio((state) => state.saved);
  const open = usePortfolio((state) => state.open);
  const detach = usePortfolio((state) => state.detach);
  const list = useSavedPortfolios();
  const save = useSavePortfolio();
  const remove = useDeleteSavedPortfolio();
  const [confirming, setConfirming] = useState<string | null>(null);

  if (list.isError && problemKind(list.error) === "persistence-not-configured") {
    return (
      <Card title={t("saved.title")}>
        <p className="text-[13px] leading-relaxed text-text-2">{t("saved.off")}</p>
      </Card>
    );
  }

  const valid = portfolioSchema.safeParse(draft).success;
  const store = (asNew: boolean) =>
    save.mutate({ portfolio: toPortfolioIn(draft), saved: asNew ? null : current }, { onSuccess: open });
  const failure = save.error ?? remove.error;
  const refusal = failure ? REFUSALS[problemKind(failure) ?? ""] : undefined;

  return (
    <Card title={t("saved.title")} subtitle={t("saved.subtitle")}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          {current ? (
            <>
              <Button size="sm" variant="primary" onClick={() => store(false)} disabled={!valid || save.isPending}>
                <Save aria-hidden className="size-3.5" />
                {t("saved.save")}
              </Button>
              <Button size="sm" onClick={() => store(true)} disabled={!valid || save.isPending}>
                {t("saved.saveNew")}
              </Button>
            </>
          ) : (
            <Button size="sm" variant="primary" onClick={() => store(true)} disabled={!valid || save.isPending}>
              <Save aria-hidden className="size-3.5" />
              {t("saved.saveFirst")}
            </Button>
          )}
          {save.isSuccess && !failure ? (
            <span role="status" className="self-center text-xs text-good-text">
              {t("saved.done")}
            </span>
          ) : null}
        </div>
        {refusal ? (
          <p role="alert" className="text-[13px] text-critical-text">
            {t(refusal)}
          </p>
        ) : failure ? (
          <ProblemAlert error={failure} />
        ) : null}
        {list.isLoading ? (
          <Skeleton className="h-16" />
        ) : list.isError ? (
          <ProblemAlert error={list.error} onRetry={() => void list.refetch()} />
        ) : list.data && list.data.items.length > 0 ? (
          <ul className="flex flex-col divide-y divide-[var(--border)] border-t hairline">
            {list.data.items.map((item) => (
              <li key={item.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 truncate text-[13px] font-medium text-text">
                    <span className="truncate">{item.portfolio.name}</span>
                    {current?.id === item.id ? <Badge tone="accent" icon={false}>{t("saved.current")}</Badge> : null}
                  </p>
                  <p className="text-xs text-muted">
                    {item.portfolio.holdings.length} {t("saved.holdings")} · {fmt.date(item.updated_at)}
                  </p>
                </div>
                {confirming === item.id ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-critical-text"
                    disabled={remove.isPending}
                    onClick={() =>
                      remove.mutate(
                        { id: item.id, version: item.version },
                        {
                          onSuccess: () => {
                            if (current?.id === item.id) detach();
                          },
                          onSettled: () => setConfirming(null),
                        },
                      )
                    }
                  >
                    {t("saved.confirmDelete")}
                  </Button>
                ) : (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => open(item)} aria-label={`${t("saved.load")} ${item.portfolio.name}`}>
                      <FolderOpen aria-hidden className="size-3.5" />
                      {t("saved.load")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(item.id)} aria-label={`${t("saved.delete")} ${item.portfolio.name}`} title={t("saved.delete")}>
                      <Trash2 aria-hidden className="size-3.5" />
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-text-2">{t("saved.empty")}</p>
        )}
      </div>
    </Card>
  );
}
