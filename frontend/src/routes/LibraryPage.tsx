import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { num, percent } from "@/lib/format";
import { decodeStrip, stripCounts } from "@/lib/strip";
import { useCurrentBook, useDeleteEbook, useLibrary, type EbookSummary } from "@/lib/books";
import { ChapterLegend, ChapterStrip } from "@/components/ChapterStrip";
import { Panel, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { SkeletonTable } from "@/components/ui/Loading";
import { Badge } from "@/components/ui/Badge";
import { Input, InputWithIcon, Select } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconChevronRight, IconMenu, IconOverview, IconPlus, IconSearch, IconTable, IconTrash } from "@/components/icons";

type ViewMode = "grid" | "list" | "table";
type LibrarySort = "title" | "title_desc" | "created_at" | "created_at_asc" | "updated_at" | "updated_at_asc";

function loadViewMode(): ViewMode {
  try {
    const value = localStorage.getItem("n2e-library-view");
    return value === "list" || value === "table" ? value : "grid";
  } catch {
    return "grid";
  }
}

function loadPageSize(): number {
  try {
    const value = Number(localStorage.getItem("n2e-library-page-size"));
    return [10, 24, 50, 100].includes(value) ? value : 24;
  } catch {
    return 24;
  }
}

function formatDate(value: string): string {
  if (!value) return "—";
  const date = new Date(value.includes("T") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}

function useDebouncedValue(value: string, delay = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function EbookBadges({ book, isCurrent }: { book: EbookSummary; isCurrent: boolean }) {
  return <div className="flex flex-wrap items-center gap-1.5">
    {isCurrent ? <Badge tone="gold">Đang làm</Badge> : null}
    {book.archived ? <Badge>Đã lưu trữ</Badge> : null}
    {book.epub_exists ? <Badge tone="celadon">EPUB</Badge> : null}
  </div>;
}

function EbookActions({ book }: { book: EbookSummary }) {
  const [currentSlug, selectBook] = useCurrentBook();
  const navigate = useNavigate();
  const del = useDeleteEbook();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typedSlug, setTypedSlug] = useState("");
  const isCurrent = currentSlug === book.slug;

  return <>
    <div className="flex shrink-0 items-center gap-1.5">
      {isCurrent ? null : <Button size="sm" variant="ghost" onClick={() => selectBook(book.slug)}>Chọn</Button>}
      <Button size="sm" variant="primary" onClick={() => { selectBook(book.slug); navigate(`/ebooks/${book.slug}/chapters`); }}>Đọc</Button>
      <Button size="sm" variant="ghost" icon={<IconChevronRight />} onClick={() => { selectBook(book.slug); navigate(`/ebooks/${book.slug}`); }} aria-label={`Mở ${book.title}`} title="Mở tổng quan" />
      <Button size="sm" variant="danger" icon={<IconTrash size={12} />} onClick={() => { setTypedSlug(""); setConfirmDelete(true); }} aria-label={`Xóa ${book.title}`} title="Xóa vĩnh viễn" />
    </div>
    <ConfirmDialog
      open={confirmDelete}
      onCancel={() => setConfirmDelete(false)}
      onConfirm={() => del.mutate(book.slug, {
        onSuccess: () => { setConfirmDelete(false); if (isCurrent) selectBook(""); toast(`Đã xóa "${book.title}".`); },
        onError: (err) => { setConfirmDelete(false); toast(err instanceof Error ? err.message : String(err), "error"); },
      })}
      title="Xóa truyện" confirmLabel="Xóa vĩnh viễn" confirmDisabled={typedSlug !== book.slug} destructive pending={del.isPending}
      body={<div className="space-y-3"><p>Xóa <span className="font-semibold">“{book.title}”</span> vĩnh viễn — gồm EPUB, bản gốc, bản dịch và dữ liệu trong DB. Không thể hoàn tác.</p><label className="block"><span className="text-xs opacity-70">Nhập slug <span data-numeric className="font-mono">“{book.slug}”</span> để xác nhận.</span><Input value={typedSlug} onChange={(e) => setTypedSlug(e.target.value)} className="mt-1.5 w-full font-mono" placeholder={book.slug} data-numeric /></label></div>}
    />
  </>;
}

function EbookGridCard({ book }: { book: EbookSummary }) {
  const [currentSlug, selectBook] = useCurrentBook();
  const done = percent(book.translated_count, book.total);
  const isCurrent = currentSlug === book.slug;
  return <Panel className={clsx("flex min-w-0 flex-col p-3.5", isCurrent && "ring-1 ring-primary/35")}>
    <div className="flex min-w-0 items-start justify-between gap-2">
      <Link to={`/ebooks/${book.slug}`} onClick={() => selectBook(book.slug)} className="line-clamp-2 min-w-0 font-display text-[15px] leading-snug font-semibold hover:text-primary">{book.title || book.slug}</Link>
      <EbookBadges book={book} isCurrent={isCurrent} />
    </div>
    <p className="mt-1 truncate text-xs opacity-60"><span data-numeric>{book.slug}</span>{book.author ? <span> · {book.author}</span> : null}</p>
    <div className="mt-4 flex items-end justify-between gap-3"><div><p className="text-[10px] tracking-[0.1em] uppercase opacity-45">Đã dịch</p><p data-numeric className="mt-0.5 text-lg leading-none font-semibold">{done}%</p></div><p data-numeric className="text-right text-xs opacity-60">{num(book.translated_count)}/{num(book.total)} chương</p></div>
    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-base-200"><div className="h-full rounded-full bg-success" style={{ width: `${done}%` }} /></div>
    <div className="mt-3 border-t border-base-300 pt-3"><EbookActions book={book} /></div>
  </Panel>;
}

function EbookTable({ books, sort, onSort }: { books: EbookSummary[]; sort: LibrarySort; onSort: (sort: LibrarySort) => void }) {
  const [currentSlug, selectBook] = useCurrentBook();

  function nextSort(descending: LibrarySort, ascending: LibrarySort): LibrarySort {
    return sort === descending ? ascending : descending;
  }

  function sortMark(descending: LibrarySort, ascending: LibrarySort) {
    if (sort === descending) return " ↓";
    if (sort === ascending) return " ↑";
    return "";
  }

  return <Panel className="overflow-hidden">
    <div className="overflow-x-auto">
      <table className="w-full min-w-[58rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-base-300 bg-base-200/60">
            <th className="px-3 py-2 text-[10px] font-semibold tracking-[0.1em] opacity-45 uppercase">
              <button type="button" className="hover:text-primary hover:opacity-100" onClick={() => onSort(nextSort("title_desc", "title"))}>Tên{sortMark("title_desc", "title")}</button>
            </th>
            <th className="px-3 py-2 text-[10px] font-semibold tracking-[0.1em] opacity-45 uppercase">Tác giả</th>
            <th className="px-3 py-2 text-[10px] font-semibold tracking-[0.1em] opacity-45 uppercase">Tiến độ</th>
            <th className="px-3 py-2 text-[10px] font-semibold tracking-[0.1em] opacity-45 uppercase">
              <button type="button" className="hover:text-primary hover:opacity-100" onClick={() => onSort(nextSort("updated_at", "updated_at_asc"))}>Cập nhật{sortMark("updated_at", "updated_at_asc")}</button>
            </th>
            <th className="px-3 py-2 text-[10px] font-semibold tracking-[0.1em] opacity-45 uppercase">
              <button type="button" className="hover:text-primary hover:opacity-100" onClick={() => onSort(nextSort("created_at", "created_at_asc"))}>Ngày tạo{sortMark("created_at", "created_at_asc")}</button>
            </th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {books.map((book) => {
            const isCurrent = currentSlug === book.slug;
            return <tr key={book.slug} className={clsx("border-b border-base-300 last:border-b-0 hover:bg-base-200/50", isCurrent && "bg-base-200/30")}>
              <td className="max-w-80 px-3 py-2.5"><div className="flex min-w-0 items-center gap-2"><Link to={`/ebooks/${book.slug}`} onClick={() => selectBook(book.slug)} className="truncate font-medium hover:text-primary">{book.title || book.slug}</Link><EbookBadges book={book} isCurrent={isCurrent} /></div><p data-numeric className="mt-0.5 truncate text-[11px] opacity-45">{book.slug}</p></td>
              <td className="max-w-52 truncate px-3 py-2.5 text-xs opacity-65">{book.author || "—"}</td>
              <td className="px-3 py-2.5"><div className="flex items-center gap-2"><div className="h-1.5 w-20 overflow-hidden rounded-full bg-base-200"><div className="h-full rounded-full bg-success" style={{ width: `${percent(book.translated_count, book.total)}%` }} /></div><span data-numeric className="text-xs opacity-60">{num(book.translated_count)}/{num(book.total)}</span></div></td>
              <td data-numeric className="whitespace-nowrap px-3 py-2.5 text-xs opacity-65">{formatDate(book.updated_at)}</td>
              <td data-numeric className="whitespace-nowrap px-3 py-2.5 text-xs opacity-65">{formatDate(book.created_at)}</td>
              <td className="px-3 py-2.5"><EbookActions book={book} /></td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  </Panel>;
}

function EbookListItem({ book }: { book: EbookSummary }) {
  const states = useMemo(() => decodeStrip(book.strip), [book.strip]);
  const counts = useMemo(() => stripCounts(book.counts), [book.counts]);
  const [currentSlug, selectBook] = useCurrentBook();
  const navigate = useNavigate();
  const done = percent(book.translated_count, book.total);
  const isCurrent = currentSlug === book.slug;
  return <article className={clsx("border-b border-base-300 px-3 py-3 last:border-b-0 hover:bg-base-200/50", isCurrent && "bg-base-200/30")}>
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Link to={`/ebooks/${book.slug}`} onClick={() => selectBook(book.slug)} className="truncate font-display text-[15px] font-semibold hover:text-primary">{book.title || book.slug}</Link><EbookBadges book={book} isCurrent={isCurrent} /></div><p className="mt-0.5 truncate text-xs opacity-60"><span data-numeric>{book.slug}</span>{book.author ? <span> · {book.author}</span> : null}{book.translate_type ? <span> · {book.translate_type}</span> : null}</p></div><EbookActions book={book} /></div>
    {book.total > 0 ? <div className="mt-3"><div className="rounded-selector bg-base-200 p-px"><ChapterStrip states={states} height={26} onSelect={(index) => { selectBook(book.slug); navigate(`/ebooks/${book.slug}/chapters/${index + 1}`); }} /></div><div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1"><ChapterLegend counts={counts} /><p className="text-[11px] opacity-60"><span data-numeric className="text-[13px] font-semibold opacity-100">{num(book.translated_count)}</span><span data-numeric className="opacity-70">/{num(book.total)}</span> chương đã dịch <span data-numeric className="ml-1.5 opacity-70">{done}%</span></p></div></div> : <p className="mt-2 text-xs opacity-50">Chưa có mục lục. Chạy bước TOC để nạp danh sách chương.</p>}
  </article>;
}

export function LibraryPage() {
  const navigate = useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<LibrarySort>("title");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(loadPageSize);
  const [view, setView] = useState<ViewMode>(loadViewMode);
  const debouncedSearch = useDebouncedValue(search);
  const { data, isPending, error } = useLibrary({ showArchived, q: debouncedSearch, sort, page, limit: pageSize });
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));
  useEffect(() => setPage(0), [debouncedSearch, showArchived, sort, pageSize]);
  useEffect(() => { try { localStorage.setItem("n2e-library-view", view); } catch { /* localStorage không khả dụng */ } }, [view]);
  useEffect(() => { try { localStorage.setItem("n2e-library-page-size", String(pageSize)); } catch { /* localStorage không khả dụng */ } }, [pageSize]);

  return <Page
    title="Thư viện"
    hint={data ? <><span data-numeric>{num(data.total)}</span> truyện{debouncedSearch ? " khớp tìm kiếm" : ""} · trang <span data-numeric>{data.page + 1}/{totalPages}</span></> : "Đang đọc thư viện"}
    actions={<><InputWithIcon icon={<IconSearch size={15} />} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Tìm tên, tác giả hoặc slug" className="w-60" aria-label="Tìm truyện" /><Select value={sort} onChange={(e) => setSort(e.target.value as LibrarySort)} aria-label="Sắp xếp thư viện" className="w-36"><option value="title">Tên A–Z</option><option value="title_desc">Tên Z–A</option><option value="updated_at">Cập nhật mới</option><option value="updated_at_asc">Cập nhật cũ</option><option value="created_at">Tạo mới</option><option value="created_at_asc">Tạo cũ</option></Select><Button variant={showArchived ? "primary" : "neutral"} onClick={() => { setShowArchived((value) => !value); setPage(0); }}>Lưu trữ {data?.archived_count ? <span data-numeric className="ml-1 opacity-60">{data.archived_count}</span> : null}</Button><div className="join" aria-label="Kiểu hiển thị"><Button size="sm" variant={view === "grid" ? "primary" : "neutral"} icon={<IconOverview />} onClick={() => setView("grid")} aria-label="Xem dạng lưới" title="Dạng lưới" /><Button size="sm" variant={view === "list" ? "primary" : "neutral"} icon={<IconMenu />} onClick={() => setView("list")} aria-label="Xem dạng danh sách" title="Dạng danh sách" /><Button size="sm" variant={view === "table" ? "primary" : "neutral"} icon={<IconTable />} onClick={() => setView("table")} aria-label="Xem dạng bảng" title="Dạng bảng" /></div><Button variant="primary" icon={<IconPlus />} onClick={() => navigate("/library/new")}>Thêm truyện</Button></>}
  >
    {isPending ? <Panel className="overflow-hidden"><SkeletonTable rows={view === "grid" ? 6 : 5} cols={view === "table" ? 6 : 5} /></Panel> : error ? <Panel><EmptyState title="Không đọc được thư viện" hint={error instanceof Error ? error.message : String(error)} /></Panel> : data?.ebooks.length === 0 ? <Panel><EmptyState title={search ? "Không có truyện nào khớp" : "Thư viện đang trống"} hint={search ? "Thử từ khóa khác hoặc bật Lưu trữ." : "Thêm truyện bằng URL mục lục để bắt đầu."} /></Panel> : <>{view === "grid" ? <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{data!.ebooks.map((book) => <EbookGridCard key={book.slug} book={book} />)}</div> : view === "table" ? <EbookTable books={data!.ebooks} sort={sort} onSort={setSort} /> : <Panel className="overflow-hidden">{data!.ebooks.map((book) => <EbookListItem key={book.slug} book={book} />)}</Panel>}<div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><p className="text-xs opacity-55">Hiển thị <span data-numeric>{num(data!.ebooks.length)}</span> trên <span data-numeric>{num(data!.total)}</span> truyện.</p><label className="flex items-center gap-1.5 text-xs opacity-60"><span>Hiện</span><Select value={String(pageSize)} onChange={(event) => setPageSize(Number(event.target.value))} aria-label="Số truyện mỗi trang" className="h-8 w-20"><option value="10">10</option><option value="24">24</option><option value="50">50</option><option value="100">100</option></Select><span>mục</span></label></div><div className="flex items-center gap-2"><Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Trước</Button><span data-numeric className="text-xs opacity-60">{page + 1}/{totalPages}</span><Button size="sm" variant="ghost" disabled={page + 1 >= totalPages} onClick={() => setPage((value) => value + 1)}>Sau</Button></div></div></>}
  </Page>;
}
