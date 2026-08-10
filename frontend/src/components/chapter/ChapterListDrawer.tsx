import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";

import { DEFAULT_FILTERS, useInfiniteChapters } from "@/lib/ebook";
import type { FindReplacePreviewItem, FindSource, SearchHit } from "@/lib/chapter";
import { num } from "@/lib/format";
import { InputWithIcon } from "@/components/ui/Field";
import { Button, Spinner } from "@/components/ui/Button";
import { Dot } from "@/components/ui/Badge";
import { DiffText } from "@/components/DiffText";
import {
  IconChevronLeft,
  IconChevronRight,
  IconClose,
  IconReplace,
  IconSearch,
} from "@/components/icons";

/* ── Luồng tìm/thay tích hợp ────────────────────────────────────────────
   Mở từ cạnh của drawer danh sách chương. Hai bước:
   1. "Tìm" — chạy `/search`, trả từng chương có khớp (toàn sách).
   2. "Xem trước" — `/find-preview scope=chapter` cho chương đang preview, hiện
      before/after kiểu VS Code. Checkbox chọn từng đoạn rồi "Áp dụng đã chọn".

   Cả `/search` lẫn `/find-preview` đều không phân biệt hoa/thường — UI không
   cung cấp nút đó. Regex hoạt động xuyên suốt. Có selector đúng MỘT nguồn
   (Bản dịch / Gốc) — search, preview, apply đều theo nguồn đang chọn; state
   được persist theo slug qua `lib/chapter.loadFindState/saveFindState`.

   Owner của tìm/thay là ChapterPage: kết quả search, preview, chọn lựa, nút
   "Mở chương" đều giữ nguyên khi đổi chương trong chế độ tìm (không điều
   hướng ngay), chỉ khác là `mode` bật về "list" để chủ động xem danh sách
   lại. */

export type FindMode = "list" | "search";

export interface ChapterFindState {
  query: string;
  replacement: string;
  regex: boolean;
  source: FindSource;
}

export interface ChapterPreviewState {
  loading: boolean;
  error: string | null;
  chapterIndex: number | null;
  items: FindReplacePreviewItem[];
  selected: Set<string>;
  applying: boolean;
}

export function ChapterListDrawer({
  open,
  onClose,
  slug,
  currentIndex,
  onSelect,
  collapsed,
  onToggleCollapsed,
  mode,
  onModeChange,
  find,
  onFindChange,
  onChangeSource,
  findReady,
  onFind,
  searchState,
  onPreviewChapter,
  previewState,
  onApplySelected,
  onTogglePreviewItem,
  onPreviewSelectAll,
  onPreviewSelectNone,
  searchHits,
  searchCount,
  onClearSearch,
  selectedIndexes,
  onToggleSelected,
  onSelectAll,
  onClearSelected,
  onBulkLocalMt,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  currentIndex: number;
  onSelect: (index: number) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mode: FindMode;
  onModeChange: (mode: FindMode) => void;
  find: ChapterFindState;
  onFindChange: (patch: Partial<ChapterFindState>) => void;
  onChangeSource: (source: FindSource) => void;
  findReady: boolean;
  onFind: () => void;
  searchState: { loading: boolean; error: string | null };
  onPreviewChapter: (index: number) => void;
  previewState: ChapterPreviewState;
  onApplySelected: () => void;
  onTogglePreviewItem: (key: string, checked: boolean) => void;
  onPreviewSelectAll: () => void;
  onPreviewSelectNone: () => void;
  searchHits: SearchHit[];
  searchCount: number;
  onClearSearch: () => void;
  selectedIndexes: Set<number>;
  onToggleSelected: (index: number) => void;
  onSelectAll: (indexes: number[]) => void;
  onClearSelected: () => void;
  onBulkLocalMt: () => void;
}) {
  const [search, setSearch] = useState("");
  const filters = useMemo(() => ({ ...DEFAULT_FILTERS, search }), [search]);
  const { data, isFetching, isPending, isError, error, fetchNextPage, hasNextPage, refetch } =
    useInfiniteChapters(slug, filters, 100);

  const active = (open || !collapsed) && mode === "list";
  const list = (data?.pages ?? []).flatMap((p) => p.rows);
  const matched = data?.pages[0]?.matched ?? 0;
  const matchingIndexes = data?.pages[0]?.indexes ?? [];
  const allMatchingSelected =
    matchingIndexes.length > 0 && matchingIndexes.every((index) => selectedIndexes.has(index));
  const reachable = hasNextPage && !isPending;

  // Tự động tải thêm trang nếu chương hiện tại nằm trong kết quả lọc nhưng chưa nạp vào danh sách
  useEffect(() => {
    if (!active || !hasNextPage || isFetching || isError) return;
    if (!search && matchingIndexes.includes(currentIndex) && !list.some((r) => r.index === currentIndex)) {
      void fetchNextPage();
    }
  }, [active, hasNextPage, isFetching, isError, search, matchingIndexes, currentIndex, list, fetchNextPage]);

  // Cuộn chương hiện tại vào giữa tầm nhìn khi đã tải xong
  const activeItemRef = useRef<HTMLLIElement | null>(null);
  const hasScrolledRef = useRef<string | null>(null);
  useEffect(() => {
    const key = `${slug}:${currentIndex}`;
    if (active && activeItemRef.current && hasScrolledRef.current !== key) {
      hasScrolledRef.current = key;
      activeItemRef.current.scrollIntoView({ block: "center" });
    }
  }, [active, slug, currentIndex, list.length]);

  // Tải trang kế khi người dùng cuộn gần đáy scroll container. Root là container
  // cuộn thật, còn element giữ nút thử lại/dòng trạng thái chỉ "tồn tại" khi
  // cuộn tới — bấm nút thử lại sẽ không kẹp phải nút bấm đang bị chờ đợi.
  const listRootRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!active) return;
    const root = listRootRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && reachable && !isFetching && !isError) {
          void fetchNextPage();
        }
      },
      { root, rootMargin: "320px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [active, reachable, isFetching, isError, fetchNextPage]);

  const handleRetry = () => {
    void refetch();
  };

  const handleSelect = (index: number) => {
    onSelect(index);
    // Mobile: drawer che gần hết màn hình nên đóng ngay; desktop giữ trạng thái.
    if (window.matchMedia("(max-width: 1023px)").matches) onClose();
  };

  const handleModeChange = (next: FindMode) => {
    onModeChange(next);
    if (next === "list" && window.matchMedia("(max-width: 1023px)").matches) onClose();
  };

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

      {/* Desktop — dải thu gọn (chỉ khi đang ở chế độ danh sách) */}
      {collapsed && mode === "list" ? (
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
            "fixed inset-y-0 right-0 z-50 flex w-80 max-w-[92vw] flex-col border-l border-base-300 bg-base-100 shadow-xl transition-transform lg:z-40 lg:w-80 lg:translate-x-0",
            open ? "translate-x-0" : "translate-x-full",
            collapsed && mode === "list" && "lg:hidden",
          )}
        >
          <div className="flex items-center justify-between border-b border-base-300 px-3 py-2.5">
            <h2 className="text-[13px] font-semibold">
              {mode === "search" ? "Tìm/thay trong truyện" : "Danh sách chương"}
            </h2>
            <div className="flex items-center gap-1">
              {mode === "search" ? (
                <button
                  type="button"
                  onClick={() => handleModeChange("list")}
                  title="Quay lại danh sách chương"
                  aria-label="Quay lại danh sách chương"
                  className="btn btn-ghost btn-xs btn-square"
                >
                  <IconChevronRight size={14} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onToggleCollapsed}
                  title="Thu gọn danh sách chương"
                  aria-label="Thu gọn danh sách chương"
                  className="btn btn-ghost btn-xs btn-square hidden lg:inline-flex"
                >
                  <IconChevronRight size={14} />
                </button>
              )}
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
            <div className="join flex w-full">
              <button
                type="button"
                onClick={() => handleModeChange("list")}
                className={clsx("btn btn-sm join-item flex-1", mode === "list" && "btn-active")}
                aria-pressed={mode === "list"}
              >
                Danh sách
              </button>
              <button
                type="button"
                onClick={() => handleModeChange("search")}
                className={clsx("btn btn-sm join-item flex-1", mode === "search" && "btn-active")}
                aria-pressed={mode === "search"}
              >
                Tìm/thay
              </button>
            </div>
          </div>

          {mode === "list" ? (
            <div className="space-y-2 border-b border-base-300 p-2">
              <InputWithIcon
                icon={<IconSearch size={14} />}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Tìm tiêu đề chương"
                className="w-full"
              />
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <button
                  type="button"
                  className="link link-hover disabled:no-underline disabled:opacity-40"
                  disabled={matchingIndexes.length === 0}
                  onClick={() =>
                    allMatchingSelected ? onClearSelected() : onSelectAll(matchingIndexes)
                  }
                >
                  {allMatchingSelected ? "Bỏ chọn tất cả" : `Chọn tất cả ${num(matched)} chương`}
                </button>
                {selectedIndexes.size > 0 ? (
                  <span data-numeric className="shrink-0 font-medium text-primary">
                    {num(selectedIndexes.size)} đã chọn
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}

          <div ref={listRootRef} className="scroll-slim flex-1 overflow-y-auto">
            {mode === "search" ? (
              <FindReplacePanel
                find={find}
                onFindChange={onFindChange}
                onChangeSource={onChangeSource}
                findReady={findReady}
                onFind={onFind}
                searchState={searchState}
                onPreviewChapter={onPreviewChapter}
                previewState={previewState}
                onApplySelected={onApplySelected}
                onTogglePreviewItem={onTogglePreviewItem}
                onPreviewSelectAll={onPreviewSelectAll}
                onPreviewSelectNone={onPreviewSelectNone}
                onOpenChapter={onSelect}
                searchHits={searchHits}
                searchCount={searchCount}
                onClearSearch={onClearSearch}
              />
            ) : isFetching && !data ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : list.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs opacity-50">
                Không có chương nào khớp.
              </p>
            ) : (
              <>
                <ul>
                  {list.map((row) => (
                    <li
                      key={row.index}
                      ref={row.index === currentIndex ? activeItemRef : undefined}
                      className={clsx(
                        "flex items-center border-l-2 hover:bg-base-200",
                        row.index === currentIndex
                          ? "border-primary bg-base-200 font-medium"
                          : "border-transparent",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="checkbox checkbox-sm ml-2.5 shrink-0"
                        checked={selectedIndexes.has(row.index)}
                        onChange={() => onToggleSelected(row.index)}
                        aria-label={`Chọn chương ${row.index}`}
                      />
                      <button
                        type="button"
                        onClick={() => handleSelect(row.index)}
                        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-1.5 text-left text-[13px]"
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
                <div ref={sentinelRef} aria-hidden="true" className="px-1 pb-1">
                  {isError ? (
                    <p className="flex items-center justify-center gap-2 px-3 py-3 text-xs">
                      <span className="text-error">
                        {error instanceof Error ? error.message : "Không tải được danh sách chương."}
                      </span>
                      <Button size="sm" onClick={handleRetry}>
                        Thử lại
                      </Button>
                    </p>
                  ) : isFetching ? (
                    <p className="flex items-center justify-center gap-2 py-3 text-[11px] opacity-60">
                      <Spinner /> Đang tải thêm chương…
                    </p>
                  ) : !hasNextPage ? (
                    <p className="py-3 text-center text-[11px] opacity-40">
                      Đã hết danh sách ({num(matched)} chương).
                    </p>
                  ) : null}
                </div>
              </>
            )}
          </div>

          {mode === "list" && selectedIndexes.size > 0 ? (
            <div className="flex items-center gap-2 border-t border-base-300 bg-base-100 p-2">
              <Button size="sm" variant="ghost" onClick={onClearSelected}>
                Bỏ chọn
              </Button>
              <Button size="sm" variant="primary" className="flex-1" onClick={onBulkLocalMt}>
                Dịch Local MT ({num(selectedIndexes.size)})
              </Button>
            </div>
          ) : null}
        </aside>
      )}
    </>
  );
}

/* ── Panel tìm/thay toàn sách ─────────────────────────────────────────── */

function FindReplacePanel({
  find,
  onFindChange,
  onChangeSource,
  findReady,
  onFind,
  searchState,
  onPreviewChapter,
  previewState,
  onApplySelected,
  onTogglePreviewItem,
  onPreviewSelectAll,
  onPreviewSelectNone,
  onOpenChapter,
  searchHits,
  searchCount,
  onClearSearch,
}: {
  find: ChapterFindState;
  onFindChange: (patch: Partial<ChapterFindState>) => void;
  onChangeSource: (source: FindSource) => void;
  findReady: boolean;
  onFind: () => void;
  searchState: { loading: boolean; error: string | null };
  onPreviewChapter: (index: number) => void;
  previewState: ChapterPreviewState;
  onApplySelected: () => void;
  onTogglePreviewItem: (key: string, checked: boolean) => void;
  onPreviewSelectAll: () => void;
  onPreviewSelectNone: () => void;
  onOpenChapter: (index: number) => void;
  searchHits: SearchHit[];
  searchCount: number;
  onClearSearch: () => void;
}) {
  const showResult = findReady && searchHits.length > 0;
  const hits = showResult ? searchHits : [];

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-base-300 p-2">
        <div className="join flex w-full">
          <button
            type="button"
            onClick={() => onChangeSource("translated")}
            className={clsx(
              "btn btn-xs join-item flex-1",
              find.source === "translated" && "btn-active",
            )}
            aria-pressed={find.source === "translated"}
          >
            Bản dịch
          </button>
          <button
            type="button"
            onClick={() => onChangeSource("raw")}
            className={clsx(
              "btn btn-xs join-item flex-1",
              find.source === "raw" && "btn-active",
            )}
            aria-pressed={find.source === "raw"}
          >
            Gốc
          </button>
        </div>
        <input
          className="input input-sm w-full"
          value={find.query}
          onChange={(e) => onFindChange({ query: e.target.value })}
          placeholder="Chuỗi cần tìm"
          aria-label="Chuỗi cần tìm trong toàn truyện"
        />
        <input
          className="input input-sm w-full"
          value={find.replacement}
          onChange={(e) => onFindChange({ replacement: e.target.value })}
          placeholder="Thay bằng (có thể để trống)"
          aria-label="Chuỗi thay thế"
        />
        <label className="flex cursor-pointer items-center gap-1.5 text-xs opacity-70">
          <input
            type="checkbox"
            className="checkbox checkbox-xs"
            checked={find.regex}
            onChange={(e) => onFindChange({ regex: e.target.checked })}
          />
          Regex
          <span className="opacity-60">(phân biệt hoa thường chưa hỗ trợ)</span>
        </label>
        <div className="flex gap-1.5">
          <Button size="sm" variant="primary" loading={searchState.loading} onClick={onFind}>
            Tìm
          </Button>
          {searchCount > 0 ? (
            <Button size="sm" variant="ghost" onClick={onClearSearch}>
              Xóa kết quả
            </Button>
          ) : null}
        </div>
      </div>

      <div className="scroll-slim flex-1 overflow-y-auto p-2">
        {searchState.loading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : searchState.error ? (
          <p className="rounded-box border border-error/30 bg-error/5 px-3 py-2 text-xs text-error">
            {searchState.error}
          </p>
        ) : !findReady ? (
          <p className="py-8 px-2 text-center text-xs opacity-50">
            Nhập chuỗi cần tìm rồi bấm Tìm — kết quả theo chương sẽ hiện ở đây.
            <br />
            Nguồn đang chọn: <span className="font-medium">{find.source === "raw" ? "Gốc" : "Bản dịch"}</span>
            {find.source === "raw" ? " (gồm cả chương chưa dịch)" : ""}.
          </p>
        ) : searchCount === 0 ? (
          <p className="py-8 text-center text-xs opacity-50">Không tìm thấy kết quả nào.</p>
        ) : (
          <ChapterHitList
            hits={hits}
            previewState={previewState}
            onPreviewChapter={onPreviewChapter}
            onApplySelected={onApplySelected}
            onTogglePreviewItem={onTogglePreviewItem}
            onPreviewSelectAll={onPreviewSelectAll}
            onPreviewSelectNone={onPreviewSelectNone}
            onOpenChapter={onOpenChapter}
          />
        )}
      </div>

      {showResult ? (
        <div className="border-t border-base-300 p-2">
          <p className="mb-1.5 text-[10px] tracking-[0.1em] uppercase opacity-40">
            Xem trước thay thế theo chương
          </p>
          <p className="text-[11px] leading-snug opacity-60">
            Bấm{" "}
            <IconReplace size={12} className="inline translate-y-[-1px]" />{" "}
            của một chương để tải preview rồi chọn đoạn cần áp dụng. Có thể preview
            nhiều chương mà không đóng khung tìm.
          </p>
        </div>
      ) : null}
    </div>
  );
}

/* ── Danh sách chương có khớp ─────────────────────────────────────────── */

function ChapterHitList({
  hits,
  previewState,
  onPreviewChapter,
  onApplySelected,
  onTogglePreviewItem,
  onPreviewSelectAll,
  onPreviewSelectNone,
  onOpenChapter,
}: {
  hits: SearchHit[];
  previewState: ChapterPreviewState;
  onPreviewChapter: (index: number) => void;
  onApplySelected: () => void;
  onTogglePreviewItem: (key: string, checked: boolean) => void;
  onPreviewSelectAll: () => void;
  onPreviewSelectNone: () => void;
  onOpenChapter: (index: number) => void;
}) {
  return (
    <ul className="space-y-1.5">
      {hits.map((hit) => {
        const previewing = previewState.chapterIndex === hit.chapter_index;
        return (
          <li
            key={hit.chapter_index}
            className={clsx(
              "rounded-box border px-2 py-1.5",
              previewing ? "border-primary/50 bg-primary/5" : "border-base-300",
            )}
          >
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onOpenChapter(hit.chapter_index)}
                className="flex min-w-0 flex-1 items-center gap-1.5 rounded-field px-1 py-1 text-left hover:bg-base-200"
                title="Mở chương này (giữ nguyên kết quả tìm)"
              >
                <span className="truncate text-[13px] font-medium">{hit.title}</span>
                <span data-numeric className="shrink-0 text-xs text-primary">
                  {num(hit.count)}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onPreviewChapter(hit.chapter_index)}
                disabled={previewState.loading}
                className="btn btn-ghost btn-xs btn-square shrink-0"
                title="Xem trước thay thế"
                aria-label={`Xem trước thay thế chương ${hit.chapter_index}`}
              >
                <IconReplace size={14} />
              </button>
            </div>
            {hit.snippets.map((s, i) => (
              <p
                key={i}
                className="mt-0.5 line-clamp-1 px-1 text-[11px] text-base-content/60"
                title={s}
              >
                {s}
              </p>
            ))}
            {previewing ? (
              previewState.loading ? (
                <div className="flex items-center justify-center gap-2 py-3 text-[11px] opacity-60">
                  <Spinner /> Đang tạo bản xem trước
                </div>
              ) : previewState.error ? (
                <p className="mt-1.5 rounded-field border border-error/30 bg-error/5 px-2 py-1.5 text-[11px] text-error">
                  {previewState.error}
                </p>
              ) : (
                <ChapterPreviewSection
                  items={previewState.items}
                  selected={previewState.selected}
                  applying={previewState.applying}
                  onApplySelected={onApplySelected}
                  onTogglePreviewItem={onTogglePreviewItem}
                  onPreviewSelectAll={onPreviewSelectAll}
                  onPreviewSelectNone={onPreviewSelectNone}
                  onOpenChapter={onOpenChapter}
                />
              )
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/* ── Preview thay thế một chương (before/after kiểu VS Code) ─────────── */

function PreviewRow({
  item,
  checked,
  disabled,
  onToggle,
}: {
  item: FindReplacePreviewItem;
  checked: boolean;
  disabled: boolean;
  onToggle: (checked: boolean) => void;
}) {
  return (
    <li
      className={clsx(
        "overflow-hidden rounded-box border",
        checked ? "border-primary/50" : "border-base-300",
      )}
    >
      <label className="flex cursor-pointer items-center gap-2 bg-base-200/50 px-2 py-1.5">
        <input
          type="checkbox"
          className="checkbox checkbox-xs"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={`Chọn đoạn ${item.para_index + 1} để thay`}
        />
        <span data-numeric className="shrink-0 text-[11px] opacity-50">
          {num(item.para_index + 1)}
        </span>
        <span className="text-[11px] font-medium opacity-80">{item.count} chỗ</span>
      </label>
      <div className="space-y-px px-2 py-1.5 font-mono text-[11px] leading-5">
        <div className="whitespace-pre-wrap break-words">
          <DiffText before={item.before} after={item.after} mode="removed" />
        </div>
        <div className="whitespace-pre-wrap break-words">
          <DiffText before={item.before} after={item.after} />
        </div>
      </div>
    </li>
  );
}

function PreviewControls({
  chapterTitle,
  selectedCount,
  totalCount,
  applying,
  disabled,
  onSelectAll,
  onSelectNone,
  onApply,
  onOpenChapter,
}: {
  chapterTitle: string;
  selectedCount: number;
  totalCount: number;
  applying: boolean;
  disabled: boolean;
  onSelectAll: () => void;
  onSelectNone: () => void;
  onApply: () => void;
  onOpenChapter: () => void;
}) {
  return (
    <div className="space-y-1.5 border-t border-base-300/70 pt-1.5">
      <div className="flex items-center justify-between gap-1">
        <p className="truncate text-[11px] opacity-70">
          {chapterTitle} · chọn {num(selectedCount)}/{num(totalCount)} đoạn
        </p>
        <button
          type="button"
          onClick={onOpenChapter}
          className="btn btn-ghost btn-xs shrink-0"
          title="Mở chương này (giữ nguyên kết quả tìm)"
        >
          Mở chương
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        <Button size="sm" disabled={disabled} onClick={onSelectAll}>
          Chọn tất cả
        </Button>
        <Button size="sm" disabled={disabled} onClick={onSelectNone}>
          Bỏ chọn
        </Button>
        <Button
          size="sm"
          variant="primary"
          loading={applying}
          disabled={disabled || selectedCount === 0}
          onClick={onApply}
        >
          Áp dụng đã chọn
        </Button>
      </div>
    </div>
  );
}

/** Đoạn preview nhúng ngay dưới chương có khớp — checkbox + before/after + áp dụng. */
function ChapterPreviewSection({
  items,
  selected,
  applying,
  onApplySelected,
  onTogglePreviewItem,
  onPreviewSelectAll,
  onPreviewSelectNone,
  onOpenChapter,
}: {
  items: FindReplacePreviewItem[];
  selected: Set<string>;
  applying: boolean;
  onApplySelected: () => void;
  onTogglePreviewItem: (key: string, checked: boolean) => void;
  onPreviewSelectAll: () => void;
  onPreviewSelectNone: () => void;
  onOpenChapter: (index: number) => void;
}) {
  const disabled = items.length === 0 || applying;

  if (items.length === 0) {
    return (
      <p className="px-1 py-1.5 text-[11px] opacity-50">
        Chương không còn đoạn nào khớp — có thể đã được thay ở lần trước.
      </p>
    );
  }

  const chapterTitle = items[0]?.chapter_title ?? "";
  const chapterIndex = items[0]?.chapter_index ?? 0;

  return (
    <div className="mt-1.5 space-y-1.5">
      <ul className="space-y-1.5">
        {items.map((item) => (
          <PreviewRow
            key={findPreviewKeyOf(item)}
            item={item}
            checked={selected.has(findPreviewKeyOf(item))}
            disabled={applying}
            onToggle={(checked) => onTogglePreviewItem(findPreviewKeyOf(item), checked)}
          />
        ))}
      </ul>
      <PreviewControls
        chapterTitle={chapterTitle}
        selectedCount={selected.size}
        totalCount={items.length}
        applying={applying}
        disabled={disabled}
        onSelectAll={onPreviewSelectAll}
        onSelectNone={onPreviewSelectNone}
        onApply={onApplySelected}
        onOpenChapter={() => onOpenChapter(chapterIndex)}
      />
    </div>
  );
}

/** Sinh khóa "chương:đoạn" — dùng chung cho owner và preview để chọn lựa khớp. */
export function findPreviewKeyOf(item: FindReplacePreviewItem): string {
  return `${item.chapter_index}:${item.para_index}`;
}
