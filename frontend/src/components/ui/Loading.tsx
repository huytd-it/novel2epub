import clsx from "clsx";
import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { Spinner } from "./Button";

/**
 * Trạng thái "đang tải" dùng chung cho cả app.
 *
 * Trước đây mỗi trang tự ghép `<Spinner /> Đang tải` với khoảng đệm khác nhau,
 * nên cùng một hành động lại trông khác nhau tùy màn hình. Gom về đây để:
 * - nhãn nào cũng có ba chấm chạy (`loading-dots`) — dấu hiệu "còn sống" rẻ
 *   nhất, thấy ngay cả khi spinner bị chìm trong nền;
 * - bảng/danh sách có khung xương thay vì khoảng trắng, để bố cục không nhảy
 *   khi dữ liệu về;
 * - có một vạch tiến độ duy nhất ở đầu app cho mọi request đang bay.
 *
 * Tất cả hiệu ứng đều tôn trọng `prefers-reduced-motion` qua khối reset trong
 * `styles/theme.css`.
 */

/** Nhãn kèm ba chấm chạy. Dùng khi đã có spinner riêng ở cạnh. */
export function LoadingLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("loading-dots", className)}>{children}</span>;
}

/**
 * Khối "đang tải" nội tuyến — spinner + nhãn.
 *
 * `size`: "sm" cho trong panel/ô nhỏ, "md" cho giữa một panel, "lg" cho cả
 * trang. `delay` (ms) giữ khối ẩn trong khoảnh khắc đầu: request trả về sau
 * 80ms mà vẫn kịp nháy spinner thì màn hình chớp một cái, khó chịu hơn là
 * không hiện gì.
 */
export function Loading({
  label = "Đang tải",
  size = "md",
  delay = 150,
  className,
}: {
  label?: string;
  size?: "sm" | "md" | "lg";
  delay?: number;
  className?: string;
}) {
  const show = useDelayedFlag(delay);
  const pad = { sm: "py-3", md: "py-12", lg: "py-20" }[size];

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={clsx(
        "flex items-center justify-center gap-2 text-sm opacity-60 transition-opacity duration-200",
        pad,
        !show && "opacity-0",
        className,
      )}
    >
      <Spinner className={size === "sm" ? "loading-xs" : undefined} />
      <LoadingLabel>{label}</LoadingLabel>
    </div>
  );
}

/** Bật `true` sau `delay` ms — tránh nháy spinner cho request về nhanh. */
function useDelayedFlag(delay: number): boolean {
  const [on, setOn] = useState(delay <= 0);
  useEffect(() => {
    if (delay <= 0) return;
    const timer = window.setTimeout(() => setOn(true), delay);
    return () => window.clearTimeout(timer);
  }, [delay]);
  return on;
}

/** Ô giữ chỗ hình chữ nhật. `w`/`h` nhận class Tailwind để gọi cho gọn. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={clsx("skeleton-box block h-4 w-full", className)} />;
}

/**
 * Khung xương cho bảng: `rows` dòng × `cols` cột, chiều rộng cột lệch nhau để
 * trông giống bảng thật chứ không phải một lưới ô vuông đều tăm tắp.
 */
export function SkeletonTable({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  const widths = ["w-8", "w-full", "w-28", "w-14", "w-12", "w-16"];
  return (
    <div role="status" aria-busy="true" aria-label="Đang tải dữ liệu" className="divide-y divide-base-300">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex items-center gap-3 px-3 py-2.5">
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton
              key={c}
              className={clsx(
                "h-3.5",
                widths[c % widths.length],
                c === 1 && "flex-1",
                // Dòng dưới mờ dần: mắt đọc từ trên xuống, phần đuôi không cần
                // giành sự chú ý.
                r > 3 && "opacity-70",
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Khung xương cho lưới thẻ (thư viện, bảng điều khiển). */
export function SkeletonCards({ count = 6, className }: { count?: number; className?: string }) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label="Đang tải dữ liệu"
      className={clsx("grid gap-3 sm:grid-cols-2 lg:grid-cols-3", className)}
    >
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-box border border-base-300 bg-base-100 p-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="mt-2 h-3 w-1/3" />
          <Skeleton className="mt-3 h-6 w-full" />
        </div>
      ))}
    </div>
  );
}

/**
 * Vạch tiến độ vô định ở mép trên app.
 *
 * Đếm cả query đang fetch lẫn mutation đang chạy, nên thao tác ghi (xếp job,
 * lưu cấu hình) cũng có phản hồi toàn cục chứ không chỉ nút bấm. Chỉ hiện sau
 * `delay` ms để thao tác nhanh không làm nháy vạch.
 */
export function GlobalLoadingBar({ delay = 200 }: { delay?: number }) {
  const busy = useIsFetching() + useIsMutating() > 0;
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!busy) {
      setVisible(false);
      return;
    }
    const timer = window.setTimeout(() => setVisible(true), delay);
    return () => window.clearTimeout(timer);
  }, [busy, delay]);

  return (
    <div
      role="progressbar"
      aria-label="Đang tải dữ liệu"
      aria-hidden={!visible}
      className={clsx(
        "pointer-events-none fixed inset-x-0 top-0 z-[60] h-0.5 overflow-hidden transition-opacity duration-200",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      {visible ? <span className="progress-indeterminate absolute inset-0 block" /> : null}
    </div>
  );
}
