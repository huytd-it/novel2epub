import clsx from "clsx";
import type { ReactNode } from "react";

export type Tone = "neutral" | "gold" | "indigo" | "celadon" | "vermilion";

const tones: Record<Tone, string> = {
  neutral: "badge-ghost",
  gold: "badge-warning badge-soft",
  indigo: "badge-info badge-soft",
  celadon: "badge-success badge-soft",
  vermilion: "badge-error badge-soft",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return <span className={clsx("badge badge-sm", tones[tone], className)}>{children}</span>;
}

const dotFill: Record<Tone, string> = {
  neutral: "bg-base-content/40",
  gold: "bg-warning",
  indigo: "bg-info",
  celadon: "bg-success",
  vermilion: "bg-error",
};

export function Dot({ tone = "neutral", pulse }: { tone?: Tone; pulse?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={clsx("size-1.5 shrink-0 rounded-full", dotFill[tone], pulse && "pulse-run")}
    />
  );
}
