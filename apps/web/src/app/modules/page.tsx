"use client";

import { useI18n } from "@/components/providers";
import { Badge, Card, PageHeader, ProblemAlert, Skeleton } from "@/components/ui";
import { useModules } from "@/lib/api/queries";

const REPOSITORY = "https://github.com/JAVIIFDEEZ/Finances/blob/development";

function codeLink(reference: string): string {
  if (reference.includes("/") || reference.endsWith(".md")) return `${REPOSITORY}/${reference}`;
  const path = reference.split(".").slice(0, 3).join("/");
  return `${REPOSITORY}/packages/investinglab/src/${path}.py`;
}

export default function ModulesPage() {
  const { t, locale } = useI18n();
  const modules = useModules(locale);
  return (
    <>
      <PageHeader title={t("modules.title")} subtitle={t("modules.subtitle")} />
      {modules.isError ? (
        <ProblemAlert error={modules.error} onRetry={() => void modules.refetch()} />
      ) : modules.isLoading ? (
        <Skeleton className="h-[480px]" />
      ) : (
        <div className="flex flex-col gap-6">
          {modules.data?.map((module) => {
            const done = module.requirements.filter((r) => r.status === "done").length;
            return (
              <Card
                key={module.slug}
                title={module.title}
                subtitle={`${module.block} · ${module.summary}`}
                actions={<Badge tone={module.complete ? "good" : "warning"}>{`${done}/${module.requirements.length} ${t("modules.complete")}`}</Badge>}
                padded={false}
              >
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <caption className="sr-only">{module.title}</caption>
                    <thead className="text-left text-xs text-text-2">
                      <tr className="border-b hairline">
                        <th className="w-14 px-4 py-2.5 font-medium">#</th>
                        <th className="px-4 py-2.5 font-medium">{t("modules.requirement")}</th>
                        <th className="px-4 py-2.5 font-medium">{t("modules.status")}</th>
                        <th className="px-4 py-2.5 font-medium">{t("modules.code")}</th>
                        <th className="px-4 py-2.5 font-medium">{t("modules.tests")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {module.requirements.map((requirement) => (
                        <tr key={requirement.id} className="border-b hairline align-top last:border-0">
                          <td className="px-4 py-3 font-mono text-text-2">{requirement.id}</td>
                          <td className="px-4 py-3">
                            <p className="text-text">{requirement.title}</p>
                            {requirement.note ? <p className="mt-1 text-xs text-muted">{requirement.note}</p> : null}
                          </td>
                          <td className="px-4 py-3">
                            <Badge tone={requirement.status === "done" ? "good" : requirement.status === "partial" ? "warning" : "neutral"}>
                              {t(`modules.status.${requirement.status}` as "modules.status.done")}
                            </Badge>
                          </td>
                          <td className="px-4 py-3">
                            <ul className="flex flex-col gap-0.5">
                              {requirement.code.map((reference) => (
                                <li key={reference}>
                                  <a href={codeLink(reference)} target="_blank" rel="noreferrer" className="font-mono text-xs text-accent hover:underline">
                                    {reference}
                                  </a>
                                </li>
                              ))}
                            </ul>
                          </td>
                          <td className="px-4 py-3">
                            <ul className="flex flex-col gap-0.5">
                              {requirement.tests.map((test) => (
                                <li key={test} className="font-mono text-xs text-text-2">
                                  {test}
                                </li>
                              ))}
                            </ul>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
