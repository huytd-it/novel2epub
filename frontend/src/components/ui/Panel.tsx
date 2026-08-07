import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

export function Panel({
  className,
  children,
  ...rest
}: { className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("card card-border border-base-300 bg-base-100", className)} {...rest}>
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  hint,
  actions,
  className,
}: {
  title: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex flex-wrap items-center justify-between gap-3 border-b border-base-300 px-3 py-2",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-[13px] font-semibold tracking-tight">{title}</h2>
        {hint ? <p className="mt-0.5 truncate text-xs opacity-60">{hint}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <p className="font-display text-base">{title}</p>
      {hint ? <p className="max-w-sm text-[13px] opacity-60">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
