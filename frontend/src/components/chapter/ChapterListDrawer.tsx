import { useState } from "react";
import clsx from "clsx";

import { DEFAULT_FILTERS, useChapters } from "@/lib/ebook";
import { num } from "@/lib/format";
import { InputWithIcon } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Button";
import { Dot } from "@/components/ui/Badge";
import { IconClose, IconSearch } from "@/components/icons";

/** Drawer bên trái: nhảy nhanh giữa các chương, tìm theo tiêu đề. */
export function ChapterListDrawer({
  open,
  onClose,
  slug,
  currentIndex,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  currentIndex: number;
  onSelect: (index: number) => void;
}) {
  const [search, setSearch] = useState("");
  const { data, isFetching } = useChapters(
    slug,
    { ...DEFAULT_FILTERS, search },
    0,
    search ? 80 : 40,
  );

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
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-50 flex w-80 max-w-[88vw] flex-col border-r border-base-300 bg-base-100 shadow-xl transition-transform lg:left-64 lg:w-72 lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between border-b border-base-300 px-3 py-2.5">
          <h2 className="text-[13px] font-semibold">Danh sách chương</h2>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-ghost btn-xs btn-square lg:hidden"
            aria-label="Đóng"
          >
            <IconClose size={14} />
          </button>
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
          ) : !data || data.rows.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs opacity-50">Không có chương nào khớp.</p>
          ) : (
            <ul>
              {data.rows.map((row) => (
                <li key={row.index}>
                  <button
                    type="button"
                    onClick={() => onSelect(row.index)}
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
    </>
  );
}
