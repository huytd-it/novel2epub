import { useEffect, useRef, useState } from "react";
import clsx from "clsx";

/**
 * Dải chương — mỗi chương một ô, tô theo trạng thái.
 *
 * Đây là chỗ duy nhất trong app trả lời được "truyện này đang ở đâu" mà không
 * phải đọc số: chỗ nào còn xám là chưa crawl, vàng là máy dịch xong chờ người,
 * lục là đã biên tập. Vẽ bằng canvas vì một bộ truyện dài có thể hơn 3000
 * chương — chừng đó thẻ DOM sẽ làm khựng cả trang danh sách.
 */

export type ChapterState = "none" | "raw" | "mt" | "edited" | "skip" | "error";

export const STATE_LABEL: Record<ChapterState, string> = {
  none: "Chưa crawl",
  raw: "Có bản gốc",
  mt: "Đã dịch máy",
  edited: "Đã biên tập",
  skip: "Bỏ qua",
  error: "Lỗi",
};

function stateColors(el: HTMLElement): Record<ChapterState, string> {
  const s = getComputedStyle(el);
  const v = (name: string) => s.getPropertyValue(name).trim();
  // Lấy thẳng biến của theme daisyUI để dải chương đổi màu cùng lúc với phần
  // còn lại của app, kể cả khi theme được chỉnh về sau.
  return {
    none: v("--color-base-300"),
    raw: v("--color-info"),
    mt: v("--color-warning"),
    edited: v("--color-success"),
    skip: v("--n2e-skip"),
    error: v("--color-error"),
  };
}

export function ChapterStrip({
  states,
  height = 26,
  onSelect,
  className,
}: {
  states: ChapterState[];
  height?: number;
  onSelect?: (index: number) => void;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ index: number; x: number } | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const draw = () => {
      const width = wrap.clientWidth;
      if (!width) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      // Chiều rộng CSS phải là 100%, KHÔNG phải số pixel vừa đo: đặt pixel
      // cứng thì canvas ép ngược chiều rộng của phần tử cha, mà chiều rộng ấy
      // lại là thứ vừa dùng để đo — khung hẹp (thanh điều hướng) sẽ phình ra
      // theo lần đo đầu tiên và không bao giờ co lại.
      canvas.style.width = "100%";
      canvas.style.height = `${height}px`;

      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const colors = stateColors(wrap);
      const n = states.length;
      if (!n) return;

      const cell = width / n;
      // Dưới 2px mỗi ô thì khe hở ăn hết màu, nên chỉ chừa khe khi còn đủ chỗ.
      const gap = cell >= 4 ? 1 : 0;
      for (let i = 0; i < n; i++) {
        ctx.fillStyle = colors[states[i]] || colors.none;
        const x = i * cell;
        ctx.fillRect(x, 0, Math.max(cell - gap, 0.6), height);
      }
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(wrap);

    // Bảng màu đổi theo data-theme trên <html>, canvas không tự vẽ lại được.
    const themeObserver = new MutationObserver(draw);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      observer.disconnect();
      themeObserver.disconnect();
    };
  }, [states, height]);

  const indexAt = (clientX: number): number | null => {
    const wrap = wrapRef.current;
    if (!wrap || !states.length) return null;
    const rect = wrap.getBoundingClientRect();
    const ratio = (clientX - rect.left) / rect.width;
    const index = Math.floor(ratio * states.length);
    if (index < 0 || index >= states.length) return null;
    return index;
  };

  return (
    <div
      ref={wrapRef}
      className={clsx("relative w-full min-w-0", className)}
      onMouseMove={(e) => {
        const index = indexAt(e.clientX);
        setHover(index === null ? null : { index, x: e.clientX });
      }}
      onMouseLeave={() => setHover(null)}
      onClick={(e) => {
        if (!onSelect) return;
        const index = indexAt(e.clientX);
        if (index !== null) onSelect(index);
      }}
    >
      <canvas
        ref={canvasRef}
        className={clsx("block rounded-selector", onSelect && "cursor-pointer")}
        role="img"
        aria-label={`Dải trạng thái ${states.length} chương`}
      />
      {hover ? (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded-field border border-base-300 bg-base-100 px-1.5 py-1 text-[11px] whitespace-nowrap shadow-lg"
          style={{
            left: hover.x,
            top: (wrapRef.current?.getBoundingClientRect().top ?? 0) - 6,
          }}
        >
          <span data-numeric className="font-semibold">
            #{hover.index + 1}
          </span>
          <span className="ml-1.5 opacity-60">{STATE_LABEL[states[hover.index]]}</span>
        </div>
      ) : null}
    </div>
  );
}

export function ChapterLegend({ counts }: { counts: Partial<Record<ChapterState, number>> }) {
  const swatch: Record<ChapterState, string> = {
    none: "bg-base-300",
    raw: "bg-info",
    mt: "bg-warning",
    edited: "bg-success",
    skip: "bg-[var(--n2e-skip)]",
    error: "bg-error",
  };
  const order: ChapterState[] = ["edited", "mt", "raw", "none", "skip", "error"];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] opacity-70">
      {order
        .filter((s) => (counts[s] ?? 0) > 0)
        .map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span
              className={clsx("size-2 rounded-selector", swatch[s])}
              aria-hidden="true"
            />
            {STATE_LABEL[s]}
            <span data-numeric className="font-medium">
              {counts[s]}
            </span>
          </span>
        ))}
    </div>
  );
}
