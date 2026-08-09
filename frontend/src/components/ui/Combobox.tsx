import { useEffect, useId, useMemo, useRef, useState } from "react";
import clsx from "clsx";

export type ComboOption = string | { label: string; value: string };

interface Normalized {
  label: string;
  value: string;
}

function normalize(o: ComboOption): Normalized {
  return typeof o === "string" ? { label: o, value: o } : o;
}

/**
 * Combobox autocomplete thay thế `<datalist>` (native không cho lọc, không
 * bấm phím mũi tên, tuỳ trình duyệt nên hành vi khác nhau). Hỗ trợ:
 * - Lọc danh sách theo từ khoá gõ vào.
 * - Phím ↑/↓ chọn, Enter xác nhận, Escape đóng, click chọn.
 * - Click ngoài / blur đóng dropdown.
 *
 * `options` là chuỗi đơn (label = value) hoặc cặp `{ label, value }` để hiển
 * thị label trong ô nhập nhưng trả về value qua `onChange`.
 */
export function Combobox({
  value,
  onChange,
  options,
  placeholder,
  className,
  onFocus,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  options: ComboOption[];
  placeholder?: string;
  className?: string;
  onFocus?: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const normalized = useMemo(() => options.map(normalize), [options]);

  const display = useMemo(() => {
    const hit = normalized.find((o) => o.value === value);
    return hit ? hit.label : value;
  }, [normalized, value]);

  const filtered = useMemo(() => {
    const q = display.trim().toLowerCase();
    if (!q) return normalized;
    return normalized.filter((o) => o.label.toLowerCase().includes(q));
  }, [normalized, display]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => setHighlighted(-1), [value, open]);

  const select = (o: Normalized) => {
    onChange(o.value);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((i) => (filtered.length ? (i + 1) % filtered.length : -1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : -1));
    } else if (e.key === "Enter") {
      if (open && highlighted >= 0 && filtered[highlighted]) {
        e.preventDefault();
        select(filtered[highlighted]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className={clsx("relative", className)}>
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-disabled={disabled}
        disabled={disabled}
        value={display}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          onFocus?.();
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        spellCheck={false}
        className="input input-sm w-full"
      />
      {open && filtered.length ? (
        <ul id={listId} className="scroll-slim absolute z-40 mt-1 max-h-60 w-full overflow-y-auto rounded-box border border-base-300 bg-base-100 p-1 shadow-lg">
          {filtered.map((o, i) => (
            <li key={o.value}>
              <button
                type="button"
                disabled={disabled}
                onMouseDown={(e) => {
                  e.preventDefault();
                  select(o);
                }}
                onMouseEnter={() => setHighlighted(i)}
                className={clsx(
                  "block w-full truncate rounded-field px-2.5 py-1.5 text-left text-[13px]",
                  i === highlighted ? "bg-base-200 font-medium" : "hover:bg-base-200/70",
                )}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
