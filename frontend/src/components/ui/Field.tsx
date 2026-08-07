import clsx from "clsx";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx("input input-sm", className)} {...rest} />;
}

/**
 * Ô nhập có icon nằm trong khung. daisyUI đặt class `input` lên PHẦN TỬ BỌC,
 * không phải lên `<input>` — icon để ngoài rồi định vị tuyệt đối sẽ bị nền của
 * input phủ mất.
 */
export function InputWithIcon({
  icon,
  className,
  ...rest
}: { icon: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className={clsx("input input-sm gap-2", className)}>
      <span className="shrink-0 opacity-50">{icon}</span>
      <input className="grow" {...rest} />
    </label>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx("textarea textarea-sm", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx("select select-sm", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <fieldset className={clsx("fieldset p-0", className)}>
      <legend className="fieldset-legend px-0 pb-1 text-[11px] tracking-wide uppercase opacity-70">
        {label}
      </legend>
      <span className="block [&>input]:w-full [&>select]:w-full [&>textarea]:w-full">
        {children}
      </span>
      {hint ? <p className="label mt-1 text-xs opacity-60">{hint}</p> : null}
    </fieldset>
  );
}

export function Checkbox({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" className={clsx("checkbox checkbox-xs", className)} {...rest} />;
}
