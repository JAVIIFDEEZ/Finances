"use client";

/**
 * Interface primitives: cards, buttons, fields, badges, stat tiles, skeletons and the
 * Problem Details alert. Quiet chrome, hairline borders; the data is the loud part.
 */

import { clsx, type ClassValue } from "clsx";
import { AlertTriangle, CheckCircle2, Info, OctagonAlert, RotateCw } from "lucide-react";
import { forwardRef, useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { twMerge } from "tailwind-merge";

import { useI18n } from "@/components/providers";
import { ApiError, failureOf, type Failure } from "@/lib/api/client";
import { useHealth } from "@/lib/api/queries";
import type { MessageKey } from "@/lib/i18n/messages";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// ── Layout ───────────────────────────────────────────────────────────

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · InvestingLab`;
  }, [title]);
  return (
    <header className="mb-6 flex flex-col gap-3 border-b hairline pb-5 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-text">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-3xl text-text-2">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  padded = true,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cn("rounded-lg border hairline bg-surface", className)}>
      {title ? (
        <div className="flex items-start justify-between gap-3 border-b hairline px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.04em] text-text-2">{title}</h2>
            {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className={cn(padded && "p-4")}>{children}</div>
    </section>
  );
}

// ── Controls ─────────────────────────────────────────────────────────

type ButtonVariant = "primary" | "secondary" | "ghost";

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" }>(
  function Button({ className, variant = "secondary", size = "md", type = "button", ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
          variant === "primary" && "bg-accent text-on-accent hover:bg-accent-strong",
          variant === "secondary" && "border hairline bg-surface-2 text-text hover:bg-surface-3",
          variant === "ghost" && "text-text-2 hover:bg-surface-2 hover:text-text",
          className,
        )}
        {...props}
      />
    );
  },
);

export function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-text-2">
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

const fieldClass =
  "h-9 w-full rounded-md border hairline bg-surface-2 px-2.5 text-sm text-text placeholder:text-muted focus-visible:border-accent";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(fieldClass, className)} {...props} />;
});

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(fieldClass, "pr-8", className)} {...props}>
      {children}
    </select>
  );
}

/** A row of mutually exclusive options (range presets, intervals, tabs of a view). */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border hairline bg-surface-2 p-0.5">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-7 rounded-[5px] px-2.5 text-xs font-medium transition-colors",
              selected ? "bg-surface text-text shadow-[0_0_0_1px_var(--border)]" : "text-text-2 hover:text-text",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Figures ──────────────────────────────────────────────────────────

type Tone = "neutral" | "good" | "warning" | "critical" | "accent";

export function Badge({ tone = "neutral", children, icon = true }: { tone?: Tone; children: ReactNode; icon?: boolean }) {
  const Icon = tone === "good" ? CheckCircle2 : tone === "warning" ? AlertTriangle : tone === "critical" ? OctagonAlert : Info;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "hairline bg-surface-2 text-text-2",
        tone === "accent" && "border-transparent bg-accent-wash text-accent-strong",
        tone === "good" && "border-transparent bg-[color-mix(in_srgb,var(--good)_14%,transparent)] text-good-text",
        tone === "warning" && "border-transparent bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] text-text",
        tone === "critical" && "border-transparent bg-[color-mix(in_srgb,var(--critical)_14%,transparent)] text-critical-text",
      )}
    >
      {icon && tone !== "neutral" && tone !== "accent" ? <Icon aria-hidden className="size-3.5" /> : null}
      {children}
    </span>
  );
}

/** Label, value and an optional signed delta: the stat-tile contract. */
export function Stat({
  label,
  value,
  detail,
  delta,
  deltaGood,
}: {
  label: string;
  value: string;
  detail?: string;
  delta?: string;
  /** Whether the delta's direction is good (colour + arrow); undefined = neutral. */
  deltaGood?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="line-clamp-2 text-xs text-text-2">{label}</span>
      <span className="text-[22px] font-semibold leading-tight tracking-tight text-text">{value}</span>
      {delta ? (
        <span
          className={cn(
            "text-xs font-medium",
            deltaGood === undefined ? "text-text-2" : deltaGood ? "text-good-text" : "text-critical-text",
          )}
        >
          {deltaGood === undefined ? "" : deltaGood ? "▲ " : "▼ "}
          {delta}
        </span>
      ) : null}
      {detail ? <span className="text-xs text-muted">{detail}</span> : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">{children}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

/** Keeps the previous render while a new result loads (no layout jump, no flash). */
export function Refreshing({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <div aria-busy={active} className={cn("transition-opacity", active && "opacity-60")}>
      {children}
    </div>
  );
}

// ── Problems ─────────────────────────────────────────────────────────

const FAILURE_MESSAGES: Record<Failure, MessageKey> = {
  api: "error.network",
  notFound: "error.notFound",
  invalid: "error.invalid",
  sources: "error.unavailable",
};

/** Problem Details mapped to a message the user can act on, with the request id. */
export function ProblemAlert({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const health = useHealth();
  const apiError = error instanceof ApiError ? error : null;
  const failure = failureOf(error);
  // While the shell's banner explains that the API does not answer, a short line is enough.
  const summary = t(failure === "api" && health.isError ? "error.apiShort" : FAILURE_MESSAGES[failure]);
  const detail = apiError?.problem?.errors?.map((e) => e.message).join(" · ") || apiError?.problem?.detail;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-[color-mix(in_srgb,var(--critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--critical)_6%,var(--surface))] p-4">
      <OctagonAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-critical-text" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-text">{t("error.title")}</p>
        <p className="mt-0.5 text-text-2">{summary}</p>
        {detail ? <p className="mt-1 break-words text-xs text-muted">{detail}</p> : null}
        {apiError?.requestId ? (
          <p className="mt-1 font-mono text-[11px] text-muted">
            {t("common.requestId")} {apiError.requestId}
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button size="sm" variant="ghost" onClick={onRetry}>
          <RotateCw aria-hidden className="size-3.5" />
          {t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}
