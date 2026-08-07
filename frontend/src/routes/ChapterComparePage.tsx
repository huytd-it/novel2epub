import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api, legacyUrl } from "@/lib/api";
import { num } from "@/lib/format";
import { chapterKey, useChapter, type Paragraph } from "@/lib/ebook";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Textarea } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { IconChevronRight, IconExternal, IconRead } from "@/components/icons";

/* ── Khung so sánh 3 cột ─────────────────────────────────────────────── */

function CompareRow({ row, position }: { row: Paragraph; position: number }) {
  const drifted = Boolean(row.mt) && Boolean(row.edited) && row.mt !== row.edited;

  return (
    <tr className="border-b border-base-300 align-top last:border-b-0">
      <td data-numeric className="w-10 px-2 py-2 text-[11px] opacity-30">
        {position}
      </td>
      <td className="w-1/3 px-2 py-2 text-[13px] leading-relaxed opacity-70">{row.raw}</td>
      <td
        className={clsx(
          "w-1/3 px-2 py-2 text-[13px] leading-relaxed",
          drifted ? "opacity-50" : "opacity-80",
        )}
      >
        {row.mt || <span className="opacity-40">—</span>}
      </td>
      <td className="w-1/3 px-2 py-2 text-[13px] leading-relaxed">
        {row.edited || <span className="opacity-40">—</span>}
        {drifted ? (
          <span
            className="ml-1.5 inline-block size-1.5 rounded-full bg-success align-middle"
            title="Khác bản dịch máy"
            aria-label="Khác bản dịch máy"
          />
        ) : null}
      </td>
    </tr>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function ChapterComparePage() {
  const { slug = "", index = "0" } = useParams();
  const chapterIndex = Number(index);
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();

  const { data, isPending, error } = useChapter(slug, chapterIndex);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Đổi chương thì bỏ luôn bản nháp đang sửa dở của chương trước.
  useEffect(() => {
    setEditing(false);
    setDraft("");
  }, [slug, chapterIndex]);

  const save = useMutation({
    mutationFn: (translated: string) =>
      api.post<{ saved: boolean; word_count: number }>(
        `/api/ui/ebooks/${slug}/chapters/${chapterIndex}/translated`,
        { body: { translated } },
      ),
    onSuccess: (res) => {
      client.invalidateQueries({ queryKey: chapterKey(slug, chapterIndex) });
      client.invalidateQueries({ queryKey: ["chapters", slug] });
      setEditing(false);
      toast(`Đã lưu — ${num(res.word_count)} từ.`);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const removeTranslation = useMutation({
    mutationFn: () =>
      api.post(`/api/ebooks/${slug}/chapters/${chapterIndex}/delete-translation`),
    onSuccess: () => {
      setConfirmDelete(false);
      client.invalidateQueries({ queryKey: chapterKey(slug, chapterIndex) });
      client.invalidateQueries({ queryKey: ["chapters", slug] });
      toast("Đã xóa bản dịch của chương này.");
    },
    onError: (err) => {
      setConfirmDelete(false);
      toast(err instanceof Error ? err.message : String(err), "error");
    },
  });

  const aiDraft = useMemo(
    () => (data?.meta?.ai_rewrite ? "Có bản nháp AI chờ duyệt" : ""),
    [data?.meta],
  );

  if (isPending) {
    return (
      <Page title="Đang tải chương">
        <div className="flex items-center justify-center gap-2 py-20 text-sm opacity-60">
          <Spinner /> Đang đọc nội dung chương
        </div>
      </Page>
    );
  }

  if (error || !data) {
    return (
      <Page title="Không mở được chương">
        <Panel>
          <EmptyState
            title={`Không đọc được chương ${chapterIndex}`}
            hint={error instanceof Error ? error.message : String(error)}
            action={<Link to={`/ebooks/${slug}`} className="btn btn-sm">Về trang truyện</Link>}
          />
        </Panel>
      </Page>
    );
  }

  const go = (target: number | null) => {
    if (target !== null) navigate(`/ebooks/${slug}/chapters/${target}`);
  };

  return (
    <Page
      title={data.title || `Chương ${data.index}`}
      hint={
        <>
          <Link to={`/ebooks/${slug}`} className="hover:text-primary">
            {slug}
          </Link>
          <span> · chương </span>
          <span data-numeric>
            {num(data.position)}/{num(data.chapter_total)}
          </span>
          {data.title_zh ? <span> · {data.title_zh}</span> : null}
          <span> · </span>
          <span data-numeric>{num(data.raw_char_count)}</span> ký tự gốc
          <span> · </span>
          <span data-numeric>{num(data.word_count)}</span> từ
        </>
      }
      actions={
        <>
          <Button disabled={data.prev_index === null} onClick={() => go(data.prev_index)}>
            Trước
          </Button>
          <Button
            disabled={data.next_index === null}
            onClick={() => go(data.next_index)}
            icon={<IconChevronRight size={14} />}
          >
            Sau
          </Button>
          <Button
            variant="primary"
            icon={<IconRead size={15} />}
            onClick={() => {
              window.location.href = legacyUrl(`/ebooks/${slug}/read/${data.index}?edit=1`);
            }}
          >
            Sửa trong Reader
          </Button>
        </>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {data.skipped ? <Badge>Bỏ qua</Badge> : null}
        {!data.has_raw ? <Badge tone="vermilion">Chưa có bản gốc</Badge> : null}
        {!data.has_translated ? <Badge tone="indigo">Chưa dịch</Badge> : null}
        {!data.has_mt_snapshot && data.has_translated ? (
          <Badge tone="neutral">Không có snapshot dịch máy</Badge>
        ) : null}
        {aiDraft ? <Badge tone="gold">{aiDraft}</Badge> : null}
        {data.url ? (
          <a
            href={data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] opacity-60 hover:text-primary hover:opacity-100"
          >
            Nguồn <IconExternal size={11} />
          </a>
        ) : null}
      </div>

      {editing ? (
        <Panel className="overflow-hidden">
          <PanelHeader
            title="Sửa toàn văn bản dịch"
            hint="Lưu nguyên văn, kể cả xuống dòng — đừng gộp dòng nếu không cố ý."
            actions={
              <>
                <Button size="sm" onClick={() => setEditing(false)}>
                  Hủy
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  loading={save.isPending}
                  onClick={() => save.mutate(draft)}
                >
                  Lưu
                </Button>
              </>
            }
          />
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="scroll-slim h-[60vh] w-full rounded-none border-0 font-read text-[15px] leading-[1.75]"
            spellCheck={false}
            aria-label="Toàn văn bản dịch"
          />
        </Panel>
      ) : (
        <Panel className="overflow-hidden">
          <PanelHeader
            title="Đối chiếu"
            hint={`${num(data.paragraphs.length)} đoạn · chấm xanh là đoạn đã khác bản dịch máy`}
            actions={
              <>
                <Button
                  size="sm"
                  disabled={!data.has_translated}
                  onClick={() => {
                    setDraft(data.translated);
                    setEditing(true);
                  }}
                >
                  Sửa toàn văn
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={!data.has_translated}
                  onClick={() => setConfirmDelete(true)}
                >
                  Xóa bản dịch
                </Button>
              </>
            }
          />
          {data.paragraphs.length === 0 || !data.has_raw ? (
            <EmptyState
              title="Chương này chưa có nội dung"
              hint="Crawl chương trước, rồi dịch, thì khung đối chiếu mới có gì để so."
            />
          ) : (
            <div className="scroll-slim overflow-x-auto">
              <table className="w-full min-w-[60rem] border-collapse">
                <thead>
                  <tr className="border-b border-base-300 bg-base-200/60 text-left">
                    <th className="w-10 px-2 py-1.5" />
                    {["Bản gốc", "Dịch máy", "Bản biên tập"].map((h) => (
                      <th
                        key={h}
                        className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.paragraphs.map((row, i) => (
                    <CompareRow key={i} row={row} position={i + 1} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      <p className="mt-3 text-xs opacity-50">
        Khung này để đối chiếu, không sửa theo từng đoạn: nó gộp các dòng trong cùng một khối
        nên số hàng ở đây không trùng số đoạn mà Reader dùng. Sửa từng đoạn thì mở Reader.
      </p>

      <ConfirmDialog
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => removeTranslation.mutate()}
        title="Xóa bản dịch"
        body={`Xóa bản dịch của chương ${data.index}? Bản gốc được giữ nên có thể dịch lại, nhưng mọi chỉnh sửa tay sẽ mất.`}
        confirmLabel="Xóa bản dịch"
        destructive
        pending={removeTranslation.isPending}
      />
    </Page>
  );
}
