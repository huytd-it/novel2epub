import { useMemo, useState } from "react";
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
import { Input, InputWithIcon } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconChevronRight, IconPlus, IconSearch, IconTrash } from "@/components/icons";

function EbookRow({ book }: { book: EbookSummary }) {
  const states = useMemo(() => decodeStrip(book.strip), [book.strip]);
  const counts = useMemo(() => stripCounts(book.counts), [book.counts]);
  const [currentSlug, selectBook] = useCurrentBook();
  const navigate = useNavigate();
  const del = useDeleteEbook();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [typedSlug, setTypedSlug] = useState("");
  const done = percent(book.translated_count, book.total);
  const isCurrent = currentSlug === book.slug;
  const canConfirm = typedSlug === book.slug;

  return (
    <article
      className={clsx(
        "border-b border-base-300 px-3 py-3 last:border-b-0 hover:bg-base-200/50",
        isCurrent && "bg-base-200/30",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/ebooks/${book.slug}`}
              onClick={() => selectBook(book.slug)}
              className="truncate font-display text-[15px] font-semibold hover:text-primary"
            >
              {book.title}
            </Link>
            {isCurrent ? <Badge tone="gold">Đang làm</Badge> : null}
            {book.archived ? <Badge>Đã lưu trữ</Badge> : null}
            {book.epub_exists ? <Badge tone="celadon">EPUB</Badge> : null}
          </div>
          <p className="mt-0.5 truncate text-xs opacity-60">
            <span data-numeric>{book.slug}</span>
            {book.author ? <span> · {book.author}</span> : null}
            {book.translate_type ? <span> · {book.translate_type}</span> : null}
          </p>
        </div>

        <div className="flex shrink-0 gap-1.5">
          {isCurrent ? null : (
            <Button size="sm" onClick={() => selectBook(book.slug)}>
              Chọn làm việc
            </Button>
          )}
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              selectBook(book.slug);
              navigate(`/ebooks/${book.slug}/chapters`);
            }}
          >
            Đọc
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<IconChevronRight />}
            onClick={() => {
              selectBook(book.slug);
              navigate(`/ebooks/${book.slug}`);
            }}
            aria-label={`Mở ${book.title}`}
          />
          <Button
            size="sm"
            variant="danger"
            icon={<IconTrash size={12} />}
            onClick={() => {
              setTypedSlug("");
              setConfirmDelete(true);
            }}
            aria-label={`Xóa ${book.title}`}
            title="Xóa vĩnh viễn"
          />
        </div>
      </div>

      {book.total > 0 ? (
        <div className="mt-3">
          <div className="rounded-selector bg-base-200 p-px">
            <ChapterStrip
              states={states}
              height={26}
              onSelect={(index) => {
                selectBook(book.slug);
                navigate(`/ebooks/${book.slug}/chapters/${index + 1}`);
              }}
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <ChapterLegend counts={counts} />
            <p className="text-[11px] opacity-60">
              <span data-numeric className="text-[13px] font-semibold opacity-100">
                {num(book.translated_count)}
              </span>
              <span data-numeric className="opacity-70">
                /{num(book.total)}
              </span>{" "}
              chương đã dịch
              <span data-numeric className="ml-1.5 opacity-70">
                {done}%
              </span>
            </p>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs opacity-50">
          Chưa có mục lục. Chạy bước TOC để nạp danh sách chương.
        </p>
      )}

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() =>
          del.mutate(book.slug, {
            onSuccess: () => {
              setConfirmDelete(false);
              if (isCurrent) selectBook("");
              toast(`Đã xóa "${book.title}".`);
            },
            onError: (err) => {
              setConfirmDelete(false);
              toast(err instanceof Error ? err.message : String(err), "error");
            },
          })
        }
        title="Xóa truyện"
        confirmLabel="Xóa vĩnh viễn"
        confirmDisabled={!canConfirm}
        destructive
        pending={del.isPending}
        body={
          <div className="space-y-3">
            <p>
              Xóa <span className="font-semibold">“{book.title}”</span> vĩnh viễn — gồm cả file
              EPUB, bản gốc, bản dịch và dữ liệu trong DB. Không thể hoàn tác.
            </p>
            <label className="block">
              <span className="text-xs opacity-70">
                Nhập slug <span data-numeric className="font-mono">“{book.slug}”</span> để xác
                nhận.
              </span>
              <Input
                value={typedSlug}
                onChange={(e) => setTypedSlug(e.target.value)}
                className="mt-1.5 w-full font-mono"
                placeholder={book.slug}
                data-numeric
              />
            </label>
          </div>
        }
      />
    </article>
  );
}

export function LibraryPage() {
  const navigate = useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const [search, setSearch] = useState("");
  const { data, isPending, error } = useLibrary(showArchived);

  const books = useMemo(() => {
    const list = data?.ebooks ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (b) =>
        b.title.toLowerCase().includes(q) ||
        b.slug.toLowerCase().includes(q) ||
        b.author.toLowerCase().includes(q),
    );
  }, [data, search]);

  const totals = useMemo(() => {
    const list = data?.ebooks ?? [];
    return list.reduce(
      (acc, b) => ({
        chapters: acc.chapters + b.total,
        translated: acc.translated + b.translated_count,
      }),
      { chapters: 0, translated: 0 },
    );
  }, [data]);

  return (
    <Page
      title="Thư viện"
      hint={
        data ? (
          <>
            <span data-numeric>{num(data.ebooks.length)}</span> truyện ·{" "}
            <span data-numeric>{num(totals.chapters)}</span> chương ·{" "}
            <span data-numeric>{percent(totals.translated, totals.chapters)}%</span> đã dịch
          </>
        ) : (
          "Đang đọc trạng thái từng truyện"
        )
      }
      actions={
        <>
          <InputWithIcon
            icon={<IconSearch size={15} />}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm truyện"
            className="w-52"
            aria-label="Tìm truyện"
          />
          <Button
            variant={showArchived ? "primary" : "neutral"}
            onClick={() => setShowArchived((v) => !v)}
          >
            Lưu trữ
            {data?.archived_count ? (
              <span data-numeric className="ml-1 opacity-60">
                {data.archived_count}
              </span>
            ) : null}
          </Button>
          <Button
            variant="primary"
            icon={<IconPlus />}
            onClick={() => navigate("/library/new")}
          >
            Thêm truyện
          </Button>
        </>
      }
    >
      <Panel className="overflow-hidden">
        {isPending ? (
          <SkeletonTable rows={5} cols={5} />
        ) : error ? (
          <EmptyState
            title="Không đọc được thư viện"
            hint={error instanceof Error ? error.message : String(error)}
          />
        ) : books.length === 0 ? (
          <EmptyState
            title={search ? "Không có truyện nào khớp" : "Thư viện đang trống"}
            hint={
              search
                ? "Thử từ khóa khác, hoặc bật Lưu trữ để tìm cả truyện đã cất đi."
                : "Thêm truyện bằng URL mục lục, rồi chạy lần lượt TOC, crawl, dịch và build."
            }
          />
        ) : (
          books.map((book) => <EbookRow key={book.slug} book={book} />)
        )}
      </Panel>

      <p className="mt-3 text-xs opacity-50">
        Bấm vào dải chương để nhảy thẳng tới chương đó. Truyện đang làm hiện luôn ở đầu thanh
        điều hướng.
      </p>
    </Page>
  );
}
