import { useMemo } from "react";

import { diffWords } from "@/lib/diff";

/**
 * Hiển thị một đoạn văn với phần khác biệt được tô.
 *
 * `mode="added"` (mặc định) hiện bản SAU: giữ nguyên phần chung, tô phần mới
 * thêm. `mode="removed"` hiện bản TRƯỚC: tô phần bị bỏ đi. Hai cột đối chiếu
 * nhau nên mỗi bên chỉ tô phần "của mình" — tô cả hai ở cùng một cột thì đọc
 * thành văn bản chắp vá không phải câu nào cả.
 */
export function DiffText({
  before,
  after,
  mode = "added",
  className,
}: {
  before: string;
  after: string;
  mode?: "added" | "removed";
  className?: string;
}) {
  const parts = useMemo(() => diffWords(before, after), [before, after]);
  const highlight = mode === "added" ? "add" : "del";
  const skip = mode === "added" ? "del" : "add";

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (part.op === skip) return null;
        if (part.op !== highlight) return <span key={i}>{part.text}</span>;
        return (
          <mark
            key={i}
            className={
              mode === "added"
                ? "rounded-sm bg-success/25 px-0.5 text-inherit"
                : "rounded-sm bg-error/20 px-0.5 text-inherit line-through decoration-1"
            }
          >
            {part.text}
          </mark>
        );
      })}
    </span>
  );
}
