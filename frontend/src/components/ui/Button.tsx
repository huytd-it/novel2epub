import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "neutral" | "ghost" | "danger";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary: "btn-primary",
  neutral: "",
  ghost: "btn-ghost",
  danger: "btn-error btn-soft",
};

const sizes: Record<Size, string> = {
  sm: "btn-xs",
  md: "btn-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  loading?: boolean;
}

export function Button({
  variant = "neutral",
  size = "md",
  icon,
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={clsx("btn", variants[variant], sizes[size], !children && "btn-square", className)}
      {...rest}
    >
      {loading ? <span className="loading loading-spinner loading-xs" /> : icon}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={clsx("loading loading-spinner loading-sm", className)} />;
}
