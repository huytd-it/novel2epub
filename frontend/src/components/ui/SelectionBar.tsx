import type { ReactNode } from "react";

import { num } from "@/lib/format";
import { Button } from "./Button";

/**
 * Thanh thao tác cho các mục ĐÃ CHỌN — CỐ ĐỊNH ở đáy màn hình.
 *
 * Lấy từ BatchBar của trang Tổng quan (EbookPage): trước đây từng trang tự ghép
 * nút "Xóa đã chọn" ngay đầu panel, chọn mục ở cuối danh sách phải cuộn ngược
 * mới bấm được. Đưa hẳn ra `fixed bottom` để chọn ở đâu cũng thao tác được tại
 * chỗ. Mỗi trang truyền các nút hành động của mình qua `children`.
 */
export function SelectionBar({
  count,
  noun = "mục",
  onClear,
  children,
}: {
  count: number;
  /** Danh từ chỉ loại mục (vd "mục glossary", "nhân vật"). */
  noun?: string;
  onClear: () => void;
  children?: ReactNode;
}) {
  return (
    <>
      {/* Chừa chỗ để thanh cố định không che mất dòng cuối bảng. */}
      <div className="h-16" aria-hidden="true" />

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-base-300 bg-base-100/95 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur md:left-64">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium">
              <span data-numeric>{num(count)}</span> {noun}
            </span>
            <Button size="sm" variant="ghost" onClick={onClear}>
              Bỏ chọn
            </Button>
          </div>

          {children ? (
            <>
              <div className="h-8 w-px bg-base-300" aria-hidden="true" />
              {children}
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}
