import { useState } from "react";
import clsx from "clsx";

import { DEFAULT_FILTERS, useChapters } from "@/lib/ebook";
import { num } from "@/lib/format";
import { InputWithIcon } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Button";
import { Dot } from "@/components/ui/Badge";
import {
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconSearch,
} from "@/components/icons";

/**
 * Danh sách chương nằm bên phải.
 *
 * Trên desktop (`lg+`) là thanh cố định: mở rộng khi `collapsed=false`, thu
 * thành dải mỏng (chỉ còn nút mở + số chương hiện tại) khi `collapsed=true`.
 * Trạng thái thu gọn nằm ở ChapterPage và được lưu vào localStorage theo slug,
 * nên giữ nguyên khi chuyển qua chương khác hoặc tải lại trang.
 *
 * Trên mobile (`<lg`) là drawer trượt từ phải: bấm chọn chương sẽ đóng lại.
 */
export function ChapterListDrawer({
  open,
  onClose,
  slug,
  currentIndex,
  onSelect,
  collapsed,
  onToggleCollapsed,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  currentIndex: number;
  onSelect: (index: number) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const [search, setSearch] = useState("");
  const { data, isFetching } = useChapters(
    slug,
    { ...DEFAULT_FILTERS, search },
    0,
    search ? 80 : 40,
  );

  const handleSelect = (index: number) => {
    onSelect(index);
    // Mobile: drawer che gần hết màn hình nên đóng ngay; desktop giữ trạng thái.
    if (window.matchMedia("(max-width: 1023px)").matches) onClose();
  };

  const list = data?.rows ?? [];

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Đóng danh sách chương"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
        />
      ) : null}

      {/* Desktop — dải thu gọn */}
      {collapsed ? (
        <aside className="fixed inset-y-0 right-0 z-40 hidden w-10 flex-col items-center gap-2 border-l border-base-300 bg-base-100 py-2 shadow-xl lg:flex">
          <button
            type="button"
            onClick={onToggleCollapsed}
            title="Mở danh sách chương"
            aria-label="Mở danh sách chương"
            className="btn btn-ghost btn-square btn-sm"
          >
            <IconChevronLeft size={16} />
          </button>
          <span data-numeric className="text-[10px] tracking-wider opacity-40">
            {num(currentIndex)}
          </span>
        </aside>
      ) : (
        <aside
          className={clsx(
            "fixed inset-y-0 right-0 z-50 flex w-80 max-w-[88vw] flex-col border-l border-base-300 bg-base-100 shadow-xl transition-transform lg:z-40 lg:w-72 lg:translate-x-0",
            open ? "translate-x-0" : "translate-x-full",
            collapsed && "lg:hidden",
          )}
        >
          <div className="flex items-center justify-between border-b border-base-300 px-3 py-2.5">
            <h2 className="text-[13px] font-semibold">Danh sách chương</h2>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={onToggleCollapsed}
                title="Thu gọn danh sách chương"
                aria-label="Thu gọn danh sách chương"
                className="btn btn-ghost btn-xs btn-square hidden lg:inline-flex"
              >
                <IconChevronRight size={14} />
              </button>
              <button
                type="button"
                onClick={onClose}
                className="btn btn-ghost btn-xs btn-square lg:hidden"
                aria-label="Đóng"
              >
                <IconClose size={14} />
              </button>
            </div>
          </div>
          <div className="border-b border-base-300 p-2">
            <InputWithIcon
              icon={<IconSearch size={14} />}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm tiêu đề chương"
              className="w-full"
              autoFocus
            />
          </div>
          <div className="scroll-slim flex-1 overflow-y-auto">
            {isFetching && !data ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : list.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs opacity-50">
                Không có chương nào khớp.
              </p>
            ) : (
              <ul>
                {list.map((row) => (
                  <li key={row.index}>
                    <button
                      type="button"
                      onClick={() => handleSelect(row.index)}
                      className={clsx(
                        "flex w-full items-center gap-2 border-l-2 px-3 py-1.5 text-left text-[13px] hover:bg-base-200",
                        row.index === currentIndex
                          ? "border-primary bg-base-200 font-medium"
                          : "border-transparent",
                      )}
                    >
                      <Dot tone={row.has_translated ? "gold" : row.has_raw ? "indigo" : "neutral"} />
                      <span data-numeric className="shrink-0 opacity-40">
                        {num(row.index)}
                      </span>
                      <span className="truncate">{row.visible_title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      )}
    </>
  );
}
