import { useEffect, useId, useMemo, useRef, useState } from "react";
import clsx from "clsx";

/**
 * Combobox autocomplete thay thế `<datalist>` (native không cho lọc, không
 * bấm phím mũi tên, tuỳ trình duyệt nên hành vi khác nhau). Hỗ trợ:
 * - Lọc danh sách theo từ khoá gõ vào.
 * - Phím ↑/↓ chọn, Enter xác nhận, Escape đóng, click chọn.
 * - Click ngoài / blur đóng dropdown.
 */
export function Combobox({
  value,
  onChange,
  options,
  placeholder,
  className,
  onFocus,
}: {
  value: string;
  onChange: (next: string) => void;
  options: string[];
  placeholder?: string;
  className?: string;
  onFocus?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [options, value]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => setHighlighted(-1), [value, open]);

  const select = (next: string) => {
    onChange(next);
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
        value={value}
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
            <li key={o}>
              <button
                type="button"
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
                {o}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
