import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { useCurrentBook } from "@/lib/books";
import { num } from "@/lib/format";
import { useChapter, type AiRevision, type ChapterCompare } from "@/lib/ebook";
import {
  applyBookReplace,
  invalidateBookSearch,
  loadFindState,
  previewBookReplace,
  saveFindState,
  useBookmark,
  useBookSearch,
  useChapterNotes,
  useCompareBlockEdit,
  useConfirmDraft,
  useCreateNote,
  useDiscardDraft,
  useReaderPreferences,
  useRevertEdits,
  useSaveChapterText,
  useSetActiveBranch,
  useUpdateChapterTitle,
  type FindReplacePreviewItem,
  type FindSource,
  type Note,
} from "@/lib/chapter";
import { Button, Spinner } from "@/components/ui/Button";
import { Textarea, Select } from "@/components/ui/Field";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { DiffText } from "@/components/DiffText";
import {
  ChapterListDrawer,
  findPreviewKeyOf,
  type ChapterFindState,
  type ChapterPreviewState,
  type FindMode,
} from "@/components/chapter/ChapterListDrawer";
import { NotesPanel } from "@/components/chapter/NotesPanel";
import { BulkPreviewDialog } from "@/components/chapter/BulkPreviewDialog";
import {
  IconBookmark,
  IconBookmarkFilled,
  IconChapters,
  IconChevronLeft,
  IconChevronRight,
  IconMinus,
  IconNote,
  IconPlus,
  IconRevert,
  IconSearch,
  IconSparkle,
} from "@/components/icons";

/* ── Bôi đen văn bản trong đoạn -> đánh dấu ghi chú ─────────────────── */

/** Bọc các đoạn khớp `note.selected_text` bằng `<mark>` có thể bấm được. */
function renderWithNotes(text: string, notes: Note[], onOpen: (note: Note) => void): ReactNode {
  if (notes.length === 0 || !text) return text;

  type Span = { start: number; end: number; note: Note };
  const spans: Span[] = [];
  for (const note of notes) {
    const needle = note.selected_text;
    if (!needle) continue;
    const start = text.indexOf(needle);
    if (start === -1) continue;
    spans.push({ start, end: start + needle.length, note });
  }
  if (spans.length === 0) return text;
  spans.sort((a, b) => a.start - b.start);

  const nodes: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, i) => {
    if (span.start < cursor) return; // đoạn chồng lấn — bỏ qua, hiếm khi xảy ra
    if (span.start > cursor) nodes.push(text.slice(cursor, span.start));
    nodes.push(
      <mark
        key={`${span.note.id}-${i}`}
        className={clsx(
          "cursor-pointer rounded-sm px-0.5",
          span.note.status === "open"
            ? "bg-warning/30 decoration-warning"
            : "bg-base-300/60 line-through decoration-1",
        )}
        onClick={(e) => {
          e.stopPropagation();
          onOpen(span.note);
        }}
      >
        {text.slice(span.start, span.end)}
      </mark>,
    );
    cursor = span.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

/* ── Popover thêm ghi chú từ vùng bôi đen ───────────────────────────── */

interface SelectionState {
  paraIndex: number;
  selectedText: string;
  paraText: string;
  x: number;
  y: number;
}

function NoteComposer({
  selection,
  onCancel,
  onSubmit,
  pending,
  onFind,
}: {
  selection: SelectionState;
  onCancel: () => void;
  onSubmit: (note: string) => void;
  pending: boolean;
  onFind: (text: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <div
      className="fixed z-50 w-72 rounded-box border border-base-300 bg-base-100 p-3 shadow-xl"
      style={{ left: selection.x, top: selection.y }}
    >
      <blockquote className="line-clamp-2 border-l-2 border-base-300 pl-2 text-xs italic opacity-60">
        {selection.selectedText}
      </blockquote>
      <Textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Chỗ này dịch có vấn đề gì?"
        rows={2}
        className="mt-1.5 w-full text-[13px]"
      />
      <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
        <Button size="sm" onClick={() => navigator.clipboard.writeText(selection.selectedText)}>Sao chép</Button>
        <Button size="sm" onClick={() => onFind(selection.selectedText)}>Tìm/thay</Button>
        <Button size="sm" onClick={onCancel}>
          Hủy
        </Button>
        <Button size="sm" variant="primary" loading={pending} onClick={() => onSubmit(text)}>
          Lưu ghi chú
        </Button>
      </div>
    </div>
  );
}

/* ── Nguồn bản dịch: hai nhánh độc lập ───────────────────────────────
   "Dịch" đọc từ BẢN GỐC và ghi thẳng vào nhánh nên phải preview + confirm.
   "Biên tập AI" đọc từ nhánh LOCAL MT và GHI TRỰC TIẾP kết quả AI vào chính
   nhánh đó (CAS mỗi chương lúc thực thi) — ghi đè bản dịch thật nên phải qua
   dialog xác nhận trước khi xếp job. Tách hẳn hai nhóm nút để không ai bấm
   nhầm "biên tập" khi định "dịch lại".                                       */

const BRANCH_ORDER = ["ai", "local_mt"] as const;

function BranchBar({
  slug,
  data,
  onAiEdit,
  aiEditPending,
}: {
  slug: string;
  data: ChapterCompare;
  onAiEdit: () => void;
  aiEditPending: boolean;
}) {
  const toast = useToast();
  const setActiveBranch = useSetActiveBranch(slug, data.index);
  const [translateAction, setTranslateAction] = useState<"translate" | "local-mt" | null>(null);

  const branchLabel = translateAction === "local-mt" ? "Local MT" : "AI";

  const switchTo = (branch: "ai" | "local_mt") => {
    if (branch === data.active_branch) return;
    setActiveBranch.mutate(branch, {
      onSuccess: () => toast(`Đã chuyển sang nhánh ${data.branches[branch].label}.`),
      onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
    });
  };

  return (
    <Panel className="mb-4 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        {BRANCH_ORDER.map((b) => {
          const st = data.branches[b];
          const isActive = b === data.active_branch;
          return (
            <div
              key={b}
              className={clsx(
                "flex items-center gap-2 rounded-field border px-2.5 py-1.5 text-[12px]",
                isActive
                  ? "border-base-content/25 bg-base-200"
                  : "border-base-300 bg-base-100",
              )}
            >
              <Badge tone={isActive ? (b === "local_mt" ? "gold" : "indigo") : "neutral"}>
                {st.label}
              </Badge>
              <span className="opacity-60">
                {st.has_text ? "có bản dịch" : "trống"}
                {st.revision > 0 ? ` · r${st.revision}` : ""}
              </span>
              {isActive ? (
                <Badge tone="gold">hoạt động</Badge>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="min-h-6 px-2 text-[11px]"
                  loading={setActiveBranch.isPending}
                  disabled={!st.has_text}
                  onClick={() => switchTo(b)}
                  title={
                    st.has_text
                      ? `Chuyển Reader/EPUB sang nhánh ${st.label}`
                      : "Nhánh này chưa có bản dịch — chưa thể chuyển"
                  }
                >
                  Chuyển
                </Button>
              )}
            </div>
          );
        })}

        <div className="h-7 w-px bg-base-300" aria-hidden="true" />

        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" disabled={!data.has_raw} onClick={() => setTranslateAction("translate")}>
            Dịch AI
          </Button>
          <Button
            size="sm"
            disabled={!data.has_raw}
            onClick={() => setTranslateAction("local-mt")}
          >
            Dịch Local MT
          </Button>
        </div>

        <div className="h-7 w-px bg-base-300" aria-hidden="true" />

        <Button
          size="sm"
          variant="primary"
          icon={<IconSparkle size={13} />}
          disabled={!data.branches.local_mt.has_text}
          loading={aiEditPending}
          onClick={onAiEdit}
          title="AI biên tập GHI TRỰC TIẾP vào nhánh Local MT (bản gốc MT giữ trong snapshot) — xem xác nhận trước khi xếp job"
        >
          Biên tập AI
        </Button>
      </div>

      <BulkPreviewDialog
        open={translateAction !== null}
        onClose={() => setTranslateAction(null)}
        slug={slug}
        action={translateAction === "local-mt" ? "local-mt" : "translate"}
        branch={translateAction === "translate" ? "ai" : ""}
        force
        indexes={[data.index]}
        title={`Dịch lại bằng ${branchLabel}`}
        body={
          <>
            Dịch lại chương {data.index} từ bản gốc vào nhánh{" "}
            <strong>{branchLabel}</strong>. Bản dịch cũ trong nhánh sẽ bị ghi đè.
          </>
        }
        confirmLabel="Dịch lại"
        onDone={() => {
          toast("Đã xếp vào hàng đợi — theo dõi ở trang Hàng đợi.");
        }}
      />
    </Panel>
  );
}

/* ── Bản nháp AI chờ duyệt ───────────────────────────────────────────── */

function DraftCard({
  draft,
  slug,
  index,
  current,
}: {
  draft: AiRevision;
  slug: string;
  index: number;
  current: string;
}) {
  const confirm = useConfirmDraft(slug, index);
  const discard = useDiscardDraft(slug, index);
  const toast = useToast();
  const [showDiff, setShowDiff] = useState(true);

  const preview = draft.payload_preview ?? "";
  const onError = (err: unknown) => toast(err instanceof Error ? err.message : String(err), "error");

  return (
    <div className="rounded-box border border-warning/40 bg-warning/5 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="gold">bản nháp {draft.engine}</Badge>
        <span data-numeric className="text-[11px] opacity-50">
          từ bản {draft.base_rev} · {draft.created_at.slice(0, 16).replace("T", " ")}
        </span>
        <div className="ml-auto flex gap-1.5">
          <Button size="sm" onClick={() => setShowDiff((v) => !v)}>
            {showDiff ? "Xem toàn văn" : "Xem khác biệt"}
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={confirm.isPending}
            onClick={() =>
              confirm.mutate(draft.id, {
                onSuccess: () => toast("Đã áp bản nháp vào bản dịch."),
                onError,
              })
            }
          >
            Áp dụng
          </Button>
          <Button
            size="sm"
            loading={discard.isPending}
            onClick={() =>
              discard.mutate(draft.id, {
                onSuccess: () => toast("Đã bỏ bản nháp."),
                onError,
              })
            }
          >
            Bỏ
          </Button>
        </div>
      </div>
      <div className="scroll-slim max-h-64 overflow-y-auto rounded-field bg-base-100 p-2.5 font-read text-[13px] leading-relaxed">
        {showDiff ? <DiffText before={current} after={preview} /> : preview}
      </div>
      {preview.length >= 2000 ? (
        <p className="mt-1 text-[11px] opacity-50">
          Xem trước bị cắt ở 2000 ký tự — áp dụng sẽ ghi toàn văn.
        </p>
      ) : null}
    </div>
  );
}

/* ── Khung đối chiếu 3 cột — cho phép sửa đoạn ───────────────────────── */

/** Đối chiếu và sửa trực tiếp ba nguồn độc lập. Local MT hiển thị phiên bản cuối
    cùng của nhánh local_mt (bao gồm kết quả AI edit), không phải snapshot cũ. */
function EditableCompareView({
  slug,
  index,
  data,
  fontFamily,
  onError,
}: {
  slug: string;
  index: number;
  data: ChapterCompare;
  fontFamily: "serif" | "sans" | "mono";
  onError: (err: unknown) => void;
}) {
  const rows = data.paragraphs;
  const edit = useCompareBlockEdit(slug, index);
  const toast = useToast();
  type Column = "raw" | "local_mt" | "ai";
  const [editing, setEditing] = useState<Record<number, Column>>({});
  const [revisions, setRevisions] = useState({
    local_mt: data.branches.local_mt.revision,
    ai: data.branches.ai.revision,
  });
  useEffect(() => {
    setRevisions({ local_mt: data.branches.local_mt.revision, ai: data.branches.ai.revision });
  }, [data.branches.local_mt.revision, data.branches.ai.revision]);

  const finishEdit = (row: number) => setEditing((current) => {
    const next = { ...current };
    delete next[row];
    return next;
  });

  const commit = (rowIndex: number, column: Column, value: string) => {
    const row = rows[rowIndex];
    if (!row) return;
    finishEdit(rowIndex);
    const before = column === "raw" ? row.raw : row[column];
    const nextValue = value.trim();
    if (nextValue === before) return;
    const branch = column === "raw" ? data.active_branch : column;
    edit.mutate({
      op: column === "raw" ? "edit_raw" : "edit_translated",
      branch,
      block: rowIndex,
      revision: column === "raw" ? data.branches[branch].revision : revisions[branch],
      raw_expected: column === "raw" ? row.raw : undefined,
      block_expected: column === "raw" ? undefined : before,
      new_text: nextValue,
    }, {
      onSuccess: (result) => {
        if (column !== "raw") setRevisions((current) => ({ ...current, [branch]: result.revision }));
        toast(`Đã sửa ${column === "raw" ? "bản gốc" : data.branches[branch].label}.`);
      },
      onError,
    });
  };

  const fontClass =
    fontFamily === "serif" ? "font-read" : fontFamily === "mono" ? "font-mono" : "font-sans";
  const columns: { key: Column; label: string }[] = [
    { key: "raw", label: "Bản gốc" },
    { key: "local_mt", label: "Local MT" },
    { key: "ai", label: "Dịch AI" },
  ];

  return (
    <div className={clsx("scroll-slim overflow-x-auto", fontClass)}>
      <table className="w-full min-w-[60rem] border-collapse">
        <thead>
          <tr className="border-b border-base-300 bg-base-200/60 text-left">
            <th className="w-10 px-2 py-1.5" />
            {columns.map(({ label }) => (
              <th
                key={label}
                className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40"
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            return (
              <tr key={i} className="border-b border-base-300 align-top last:border-b-0">
                <td data-numeric className="w-10 px-2 py-2 text-[11px] opacity-30">
                  {i + 1}
                </td>
                {columns.map(({ key }) => {
                  const value = key === "raw" ? row.raw : row[key];
                  return <td key={key} className="w-1/3 px-2 py-2 text-[13px] leading-relaxed">
                    {editing[i] === key ? (
                      <CompareCellEditor
                        autoFocus
                        defaultValue={value}
                        disabled={edit.isPending}
                        fontFamily={fontFamily}
                        onCommit={(next) => commit(i, key, next)}
                        onCancel={() => finishEdit(i)}
                      />
                    ) : (
                      <button
                        type="button"
                        className="block min-h-6 w-full cursor-text rounded-field px-1 text-left hover:bg-base-200"
                        disabled={edit.isPending || (key !== "raw" && !data.branches[key].has_text)}
                        onClick={() => setEditing((current) => ({ ...current, [i]: key }))}
                        title={`Sửa ${key === "raw" ? "bản gốc" : data.branches[key].label}`}
                      >
                        {value || <span className="opacity-40">—</span>}
                      </button>
                    )}
                  </td>;
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CompareCellEditor({ defaultValue, onCommit, onCancel, autoFocus, disabled, fontFamily }: {
  defaultValue: string;
  onCommit: (value: string) => void;
  onCancel: () => void;
  autoFocus?: boolean;
  disabled?: boolean;
  fontFamily: "serif" | "sans" | "mono";
}) {
  const [value, setValue] = useState(defaultValue);
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${element.scrollHeight}px`;
    if (autoFocus) element.focus();
  }, [value, autoFocus]);
  return <textarea
    ref={ref}
    value={value}
    disabled={disabled}
    onChange={(event) => setValue(event.target.value)}
    onBlur={(event) => onCommit(event.target.value)}
    onKeyDown={(event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) event.currentTarget.blur();
      if (event.key === "Escape") { event.preventDefault(); onCancel(); }
    }}
    className={clsx(
      "textarea textarea-bordered textarea-sm w-full resize-none overflow-hidden text-[13px]",
      fontFamily === "serif" && "font-read",
      fontFamily === "mono" && "font-mono",
      fontFamily === "sans" && "font-sans",
    )}
    aria-label="Sửa đoạn"
  />;
}

/** Tab Gốc — render bản gốc theo khối, có empty state rõ ràng. */
function RawContentView({ text }: { text: string }) {
  if (!text.trim()) {
    return (
      <p className="px-4 py-10 text-center text-sm opacity-50">
        Chương chưa có nội dung gốc.
      </p>
    );
  }
  const blocks = text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  return (
    <div className="scroll-slim max-h-[75vh] overflow-y-auto px-4 py-3">
      <div className="space-y-3">
        {blocks.map((block, i) => (
          <p
            key={i}
            data-numeric
            className="whitespace-pre-wrap font-read text-[15px] leading-relaxed text-base-content/80"
          >
            {block}
          </p>
        ))}
      </div>
    </div>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function ChapterPage() {
  const { slug = "", index = "0" } = useParams();
  const chapterIndex = Number(index);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const toast = useToast();
  const [, selectBook] = useCurrentBook();
  const queryClient = useQueryClient();

  const { data, isPending, error } = useChapter(slug, chapterIndex);
  const { data: notes } = useChapterNotes(slug, chapterIndex);
  const saveChapterText = useSaveChapterText(slug, chapterIndex);
  const updateTitle = useUpdateChapterTitle(slug, chapterIndex);
  const revertEdits = useRevertEdits(slug, chapterIndex);
  const createNote = useCreateNote(slug, chapterIndex);

  // `?edit=1` mở sẵn chế độ sửa. Xoá param ngay sau khi đọc để URL không
  // "dính" chế độ sửa khi chia sẻ hay bookmark.
  const [editMode, setEditMode] = useState(() => searchParams.get("edit") === "1");
  useEffect(() => {
    if (searchParams.get("edit") === "1") setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ chạy 1 lần lúc mount
  }, []);

  const [view, setView] = useState<"read" | "compare" | "raw">("read");
  const [readerPrefs, setReaderPrefs] = useReaderPreferences();
  const { fontSize } = readerPrefs;
  const [bookmark, setBookmark] = useBookmark(slug);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [selectedChapterIndexes, setSelectedChapterIndexes] = useState<Set<number>>(new Set());
  const [bulkLocalMtOpen, setBulkLocalMtOpen] = useState(false);
  const [aiEditOpen, setAiEditOpen] = useState(false);
  // Trạng thái thu gọn danh sách chương (desktop) — lưu theo slug để giữ nguyên
  // khi chuyển chương và khi tải lại trang.
  const [chaptersCollapsed, setChaptersCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(`n2e-chapters-collapsed:${slug}`) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      setChaptersCollapsed(localStorage.getItem(`n2e-chapters-collapsed:${slug}`) === "1");
    } catch {
      setChaptersCollapsed(false);
    }
  }, [slug]);
  const toggleChaptersCollapsed = () => {
    setChaptersCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(`n2e-chapters-collapsed:${slug}`, next ? "1" : "0");
      } catch {
        /* bỏ qua khi không truy cập được localStorage */
      }
      return next;
    });
  };
  const [notesOpen, setNotesOpen] = useState(false);
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [documentDraft, setDocumentDraft] = useState("");
  const [documentRevision, setDocumentRevision] = useState(0);
  const contentRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const [loadedKey, setLoadedKey] = useState("");

  const chapterDataKey = data ? `${slug}:${chapterIndex}:${data.active_branch}` : "";
  const dirty = Boolean(data && loadedKey === chapterDataKey && documentDraft !== data.translated);

  useEffect(() => {
    if (!data) return;
    const key = `${slug}:${chapterIndex}:${data.active_branch}`;
    if (loadedKey !== key) {
      setLoadedKey(key);
      setDocumentDraft(data.translated);
      setDocumentRevision(data.revision);
    }
  }, [slug, chapterIndex, data, loadedKey]);

  useLayoutEffect(() => {
    if (!editMode || !editorRef.current) return;
    const editor = editorRef.current;
    editor.style.height = "0px";
    editor.style.height = `${editor.scrollHeight}px`;
  }, [documentDraft, editMode, fontSize, readerPrefs.fontFamily, readerPrefs.lineHeight]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (slug) selectBook(slug);
  }, [slug, selectBook]);

  useEffect(() => setSelection(null), [slug, chapterIndex]);

  /* ── Tìm/thay tích hợp trong drawer Danh sách chương ─────────────────
     State sở hữu ở đây (ChapterPage) nên không mất khi đổi chương: route giữ
     component mount khi điều hướng giữa `/chapters/:index`. Query, replacement,
     regex được persist theo slug trong localStorage. Search, preview, chọn lựa
     áp dụng đều tự động hiển thị "chapter thật" của kết quả đang xem. */

  const [findMode, setFindMode] = useState<FindMode>("list");
  const [findState, setFindState] = useState<ChapterFindState>(() => loadFindState(slug));
  const [findSubmitted, setFindSubmitted] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const previewRequestRef = useRef(0);

  const updateFind = (patch: Partial<ChapterFindState>) => {
    setFindState((prev) => {
      const next = { ...prev, ...patch };
      saveFindState(slug, next);
      return next;
    });
  };

  const { data: findHits, isFetching: findLoading, error: findError } = useBookSearch(
    slug,
    findQuery,
    findState.regex,
    findState.source,
  );

  // Khi chuyển sang truyện khác, đừng mang theo kết quả tìm của truyện cũ;
  // nạp lại query/replacement đã lưu riêng cho truyện mới.
  useEffect(() => {
    setFindState(loadFindState(slug));
    setFindQuery("");
    setFindSubmitted(false);
    setPreviewChapter(null);
    setPreviewItems([]);
    setPreviewSelected(new Set());
    setSelectedChapterIndexes(new Set());
    setBulkLocalMtOpen(false);
  }, [slug]);

  const runFind = () => {
    const q = findState.query.trim();
    if (!q) return;
    setFindQuery(q);
    setFindSubmitted(true);
  };

  const clearSearchResults = () => {
    setFindQuery("");
    setFindSubmitted(false);
  };

  // Đổi nguồn (Bản dịch ↔ Gốc) làm kết quả cũ vô nghĩa — ẩn ngay cho tới khi
  // bấm Tìm lại trên nguồn mới.
  const changeFindSource = (source: FindSource) => {
    if (source === findState.source) return;
    previewRequestRef.current += 1;
    setPreviewLoading(false);
    updateFind({ source });
    setFindQuery("");
    setFindSubmitted(false);
    setPreviewChapter(null);
    setPreviewItems([]);
    setPreviewSelected(new Set());
    setView(source === "raw" ? "raw" : "read");
  };

  // Kết quả chỉ hiển thị khi chuỗi đang gõ khớp đúng chuỗi đã submit — sửa
  // query giữa chừng là ẩn ngay thay vì hiện kết quả cũ lệch chuỗi.
  const findReady =
    findSubmitted && !findLoading && !findError && findState.query.trim() === findQuery;
  const searchCount = findReady ? (findHits?.length ?? 0) : 0;

  /* Preview thay thế theo chương — bấm icon trên từng hit, không điều hướng.
     Dùng đúng query đã submit (findQuery) để khớp danh sách hit đang hiện;
     replacement luôn lấy giá trị mới nhất vì nó không đổi danh sách hit. */
  const [previewChapter, setPreviewChapter] = useState<number | null>(null);
  const [previewItems, setPreviewItems] = useState<FindReplacePreviewItem[]>([]);
  const [previewSelected, setPreviewSelected] = useState<Set<string>>(new Set());
  const [previewApplying, setPreviewApplying] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const loadChapterPreview = async (chapterIndex: number) => {
    const q = findQuery.trim();
    if (!q) return;
    const requestId = ++previewRequestRef.current;
    setPreviewChapter(chapterIndex);
    setPreviewItems([]);
    setPreviewSelected(new Set());
    setPreviewError(null);
    setPreviewLoading(true);
    try {
      const result = await previewBookReplace(
        slug,
        q,
        findState.replacement,
        findState.regex,
        "chapter",
        chapterIndex,
        findState.source,
      );
      if (requestId !== previewRequestRef.current) return;
      setPreviewItems(result.items);
      setPreviewSelected(new Set(result.items.map(findPreviewKeyOf)));
      if (result.truncated) toast("Preview giới hạn 300 đoạn; hãy thu hẹp chuỗi tìm.", "error");
    } catch (err) {
      if (requestId === previewRequestRef.current) {
        setPreviewError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (requestId === previewRequestRef.current) setPreviewLoading(false);
    }
  };

  const applyPreview = async () => {
    if (!previewChapter || previewItems.length === 0) return;
    const selectedItems = previewItems.filter((item) => previewSelected.has(findPreviewKeyOf(item)));
    if (selectedItems.length === 0) return;
    setPreviewApplying(true);
    try {
      const result = await applyBookReplace(
        slug,
        findQuery.trim(),
        findState.replacement,
        findState.regex,
        selectedItems,
        findState.source,
      );
      toast(
        `Đã thay ${result.replaced} chỗ trong ${result.chapters} chương${
          result.stale ? `; bỏ qua ${result.stale} đoạn đã đổi` : ""
        }.`,
      );
      const appliedKeys = new Set(selectedItems.map((item) => findPreviewKeyOf(item)));
      setPreviewItems((items) =>
        items.filter((item) => !appliedKeys.has(findPreviewKeyOf(item))),
      );
      setPreviewSelected((prev) => {
        const next = new Set(prev);
        for (const key of appliedKeys) next.delete(key);
        return next;
      });
      // Nội dung đang xem có thể đã đổi — cập nhật chapter/chapter list ngay.
      invalidateBookSearch(queryClient, slug);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPreviewApplying(false);
    }
  };

  const applyAllMatches = async () => {
    const q = findQuery.trim();
    if (!q || previewApplying) return;
    const sourceLabel = findState.source === "raw" ? "bản gốc" : "bản dịch";
    if (!window.confirm(`Thay tất cả kết quả đang khớp trong ${sourceLabel} của toàn truyện?`)) return;
    setPreviewApplying(true);
    try {
      const result = await applyBookReplace(
        slug,
        q,
        findState.replacement,
        findState.regex,
        [],
        findState.source,
        true,
      );
      toast(`Đã thay ${result.replaced} chỗ trong ${result.chapters} chương.`);
      setPreviewChapter(null);
      setPreviewItems([]);
      setPreviewSelected(new Set());
      invalidateBookSearch(queryClient, slug);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPreviewApplying(false);
    }
  };

  const togglePreviewItem = (key: string, checked: boolean) => {
    setPreviewSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const previewSelectAll = () => {
    setPreviewSelected(new Set(previewItems.map(findPreviewKeyOf)));
  };

  const previewSelectNone = () => {
    setPreviewSelected(new Set());
  };

  const previewState: ChapterPreviewState = {
    loading: previewLoading,
    error: previewError,
    chapterIndex: previewChapter,
    items: previewItems,
    selected: previewSelected,
    applying: previewApplying,
  };

  const openFindMode = (query?: string) => {
    setFindMode("search");
    setChaptersCollapsed(false);
    if (query) updateFind({ query });
    setChaptersOpen(true);
  };

  const notesByPara = useMemo(() => {
    const map = new Map<number, Note[]>();
    for (const n of notes ?? []) {
      if (!map.has(n.para_index)) map.set(n.para_index, []);
      map.get(n.para_index)!.push(n);
    }
    return map;
  }, [notes]);

  const openNoteCount = useMemo(
    () => (notes ?? []).filter((n) => n.status === "open").length,
    [notes],
  );

  const drafts = useMemo(
    () => (data?.ai_revisions ?? []).filter((r) => r.status === "pending" && r.payload_preview),
    [data?.ai_revisions],
  );

  const handleMouseUp = () => {
    if (editMode || view !== "read") return;
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? "";
    if (!sel || !text || sel.rangeCount === 0) return;
    const anchor = sel.anchorNode;
    const paraEl = (anchor instanceof Element ? anchor : anchor?.parentElement)?.closest(
      "[data-para-index]",
    );
    if (!paraEl || !contentRef.current?.contains(paraEl)) return;
    const paraIndex = Number(paraEl.getAttribute("data-para-index"));
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    setSelection({
      paraIndex,
      selectedText: text,
      paraText: paraEl.textContent ?? "",
      x: Math.min(Math.max(8, rect.left), window.innerWidth - 300),
      y: rect.bottom + 8,
    });
  };

  const saveDocument = () => {
    if (!dirty || saveChapterText.isPending) return;
    saveChapterText.mutate(
      { translated: documentDraft, expectedRev: documentRevision },
      {
        onSuccess: (result) => {
          setDocumentRevision(result.revision);
          toast("Đã lưu toàn bộ chương.");
        },
        onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
      },
    );
  };

  const go = (target: number | null) => {
    if (target === null) return;
    if (dirty && !window.confirm("Chương có thay đổi chưa lưu. Rời chương và bỏ thay đổi?")) return;
    navigate(`/ebooks/${slug}/chapters/${target}`);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveDocument();
      } else if (modifier && ["f", "h"].includes(event.key.toLowerCase())) {
        event.preventDefault();
        openFindMode();
      } else if (event.altKey && event.key === "1") setView("read");
      else if (event.altKey && event.key === "2") {
        setView("read");
        setEditMode(true);
      } else if (event.altKey && event.key === "3") setView("compare");
      else if (event.altKey && event.key === "4") setView("raw");
      else if (event.altKey && event.key === "ArrowLeft") go(data?.prev_index ?? null);
      else if (event.altKey && event.key === "ArrowRight") go(data?.next_index ?? null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dirty, saveChapterText.isPending, documentDraft, documentRevision, data, openFindMode]);

  if (isPending) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center gap-2 text-sm opacity-60">
        <Spinner /> Đang tải chương
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 text-center">
        <p className="font-display text-lg">Không mở được chương {chapterIndex}</p>
        <p className="mt-2 text-sm opacity-60">
          {error instanceof Error ? error.message : String(error)}
        </p>
        <Button className="mt-4" onClick={() => navigate(`/ebooks/${slug}`)}>
          Về trang truyện
        </Button>
      </div>
    );
  }

  const isBookmarked = bookmark === chapterIndex;

  return (
    <div
      className={clsx("min-h-screen", chaptersCollapsed ? "lg:pr-10" : "lg:pr-80")}
    >
      {/* ── Thanh công cụ ─────────────────────────────────────────── */}
      <div className="sticky top-0 z-30 border-b border-base-300 bg-base-100/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1100px] flex-wrap items-center gap-2 px-3 py-2 sm:justify-between">
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              icon={<IconChapters size={15} />}
              onClick={() => {
                setChaptersCollapsed(false);
                setChaptersOpen(true);
              }}
              aria-label="Danh sách chương"
            />
            <Button
              size="sm"
              variant="ghost"
              icon={<IconChevronLeft size={14} />}
              disabled={data.prev_index === null}
              onClick={() => go(data.prev_index)}
              aria-label="Chương trước"
            />
            <span data-numeric className="px-1 text-xs opacity-50">
              #{num(data.index)}
            </span>
            <Button
              size="sm"
              variant="ghost"
              icon={<IconChevronRight size={14} />}
              disabled={data.next_index === null}
              onClick={() => go(data.next_index)}
              aria-label="Chương sau"
            />
          </div>

          <div role="tablist" className="tabs tabs-box tabs-xs">
            <button
              role="tab"
              type="button"
              className={clsx("tab", view === "read" && "tab-active")}
              onClick={() => setView("read")}
            >
              Đọc
            </button>
            <button
              role="tab"
              type="button"
              className={clsx("tab", view === "compare" && "tab-active")}
              onClick={() => setView("compare")}
            >
              Đối chiếu
            </button>
            <button
              role="tab"
              type="button"
              className={clsx("tab", view === "raw" && "tab-active")}
              onClick={() => setView("raw")}
            >
              Gốc
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-1">
            <Button
              size="sm"
              variant="ghost"
              icon={<IconSearch size={15} />}
              className="min-h-9 min-w-9 px-2 sm:min-h-0 sm:min-w-0"
              onClick={() => openFindMode()}
              aria-label="Tìm/thay trong truyện"
              title="Tìm/thay trong truyện (Ctrl+F / Ctrl+H)"
            />
            <div className="relative">
              <Button
                size="sm"
                variant="ghost"
                icon={<IconNote size={15} />}
                onClick={() => setNotesOpen(true)}
                aria-label="Ghi chú"
              />
              {openNoteCount > 0 ? (
                <span
                  data-numeric
                  className="absolute -top-0.5 -right-0.5 flex size-3.5 items-center justify-center rounded-full bg-warning text-[9px] font-medium text-warning-content"
                >
                  {openNoteCount > 9 ? "9+" : openNoteCount}
                </span>
              ) : null}
            </div>
            <Button
              size="sm"
              variant="ghost"
              icon={isBookmarked ? <IconBookmarkFilled size={15} /> : <IconBookmark size={15} />}
              onClick={() => setBookmark(isBookmarked ? null : chapterIndex)}
              aria-label={isBookmarked ? "Bỏ đánh dấu" : "Đánh dấu chương này"}
            />
            <div className="mx-1 flex items-center gap-0.5 rounded-field border border-base-300 px-0.5">
              <Button
                size="sm"
                variant="ghost"
                icon={<IconMinus size={13} />}
                onClick={() => setReaderPrefs({ fontSize: fontSize - 1 })}
                aria-label="Giảm cỡ chữ"
              />
              <span data-numeric className="w-5 text-center text-[11px] opacity-60">
                {fontSize}
              </span>
              <Button
                size="sm"
                variant="ghost"
                icon={<IconPlus size={13} />}
                onClick={() => setReaderPrefs({ fontSize: fontSize + 1 })}
                aria-label="Tăng cỡ chữ"
              />
            </div>
            <Select
              aria-label="Font đọc"
              value={readerPrefs.fontFamily}
              onChange={(e) => setReaderPrefs({ fontFamily: e.target.value as "serif" | "sans" | "mono" })}
              className="hidden h-7 w-24 min-h-7 sm:block"
            >
              <option value="serif">Serif</option>
              <option value="sans">Sans</option>
              <option value="mono">Mono</option>
            </Select>
            <Select
              aria-label="Giãn dòng"
              value={readerPrefs.lineHeight}
              onChange={(e) => setReaderPrefs({ lineHeight: Number(e.target.value) })}
              className="hidden h-7 w-20 min-h-7 sm:block"
            >
              <option value="1.5">1.5×</option>
              <option value="1.8">1.8×</option>
              <option value="2.1">2.1×</option>
            </Select>
            <Button
              size="sm"
              variant={editMode ? "primary" : "ghost"}
              disabled={view !== "read"}
              onClick={() => setEditMode((v) => !v)}
            >
              {editMode ? "Đang sửa" : "Sửa"}
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1100px] px-4 py-5">
        <BranchBar
          slug={slug}
          data={data}
          aiEditPending={false}
          onAiEdit={() => setAiEditOpen(true)}
        />

        {drafts.length > 0 ? (
          <Panel className="mb-4 overflow-hidden">
            <PanelHeader
              title={`Bản nháp AI chờ duyệt (${drafts.length})`}
              hint="Khối legacy của workflow cũ (sinh bản nháp chờ duyệt) — biên tập AI giờ ghi trực tiếp nên bản nháp ở đây không tự áp; chấp nhận hoặc bỏ đi."
            />
            <div className="space-y-2.5 p-3">
              {drafts.map((d) => (
                <DraftCard
                  key={d.id}
                  draft={d}
                  slug={slug}
                  index={chapterIndex}
                  current={data.translated}
                />
              ))}
            </div>
          </Panel>
        ) : null}
      </div>

      {/* ── Nội dung ──────────────────────────────────────────────── */}
      {view === "compare" ? (
        <div className="mx-auto max-w-[1100px] px-4 pb-10">
          <Panel className="overflow-hidden">
            <PanelHeader
              title="Đối chiếu"
              hint={`${num(data.paragraphs.length)} đoạn · bấm vào ô để sửa đúng nguồn`}
            />
            {data.has_raw ? (
              <EditableCompareView
                slug={slug}
                index={chapterIndex}
                data={data}
                fontFamily={readerPrefs.fontFamily}
                onError={(err) => toast(err instanceof Error ? err.message : String(err), "error")}
              />
            ) : (
              <p className="px-4 py-10 text-center text-sm opacity-50">
                Chương chưa có bản gốc để đối chiếu.
              </p>
            )}
          </Panel>
          <p className="mt-3 text-xs opacity-50">
            Bấm vào Bản gốc, Local MT hoặc Dịch AI để sửa trực tiếp; Ctrl+Enter để lưu.
            Local MT là phiên bản cuối cùng của nhánh, bao gồm nội dung đã được AI biên tập.
          </p>
        </div>
      ) : view === "raw" ? (
        <div className="mx-auto max-w-[1100px] px-4 pb-10">
          <Panel className="overflow-hidden">
            <PanelHeader
              title="Bản gốc"
              hint={
                data.has_raw
                  ? `${num(data.raw_char_count)} ký tự · chương chưa dịch vẫn xem được`
                  : "Chương chưa crawl được nội dung gốc."
              }
            />
            {data.has_raw ? (
              <RawContentView text={data.raw} />
            ) : (
              <p className="px-4 py-10 text-center text-sm opacity-50">
                Chương chưa có bản gốc. Chạy bước Crawl ở trang truyện trước.
              </p>
            )}
          </Panel>
        </div>
      ) : (
        <div
          className="mx-auto px-4 pb-16"
          style={{ maxWidth: `${readerPrefs.contentWidth}px` }}
          ref={contentRef}
          onMouseUp={handleMouseUp}
        >
          <ChapterTitle
            title={data.title}
            editMode={editMode}
            onSave={(t) =>
              updateTitle.mutate(t, { onError: () => toast("Không lưu được tiêu đề.", "error") })
            }
          />

          {editMode ? (
            <div className="mb-5">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className={dirty ? "text-warning" : "opacity-50"}>{dirty ? "Có thay đổi chưa lưu" : "Đã đồng bộ"}</span>
                <Button size="sm" variant="primary" disabled={!dirty} loading={saveChapterText.isPending} onClick={saveDocument}>Lưu chương <span className="opacity-60">Ctrl+S</span></Button>
              </div>
              <textarea
                ref={editorRef}
                value={documentDraft}
                onChange={(e) => setDocumentDraft(e.target.value)}
                className={clsx(
                  "textarea textarea-bordered min-h-[60vh] w-full resize-none overflow-hidden",
                  readerPrefs.fontFamily === "serif" && "font-read",
                  readerPrefs.fontFamily === "mono" && "font-mono",
                  readerPrefs.fontFamily === "sans" && "font-sans",
                )}
                style={{ fontSize: `${fontSize}px`, lineHeight: readerPrefs.lineHeight }}
                spellCheck
                aria-label="Biên tập toàn bộ chương"
              />
              <p className="mt-2 text-xs opacity-50">Bạn có thể thêm, bớt hoặc xóa đoạn trực tiếp bằng xuống dòng. Lưu dùng khóa revision để tránh ghi đè thay đổi mới hơn.</p>
            </div>
          ) : !data.has_translated ? (
            <div className="rounded-box border border-base-300 bg-base-200/40 px-6 py-14 text-center">
              <p className="font-display text-base">
                {data.branches.ai.has_text || data.branches.local_mt.has_text
                  ? `Nhánh ${data.branches[data.active_branch].label} đang hoạt động chưa có nội dung`
                  : "Chương này chưa có bản dịch"}
              </p>
              <p className="mt-2 text-sm opacity-60">
                {data.branches.ai.has_text || data.branches.local_mt.has_text
                  ? `Đã có bản ${data.branches[data.active_branch === "ai" ? "local_mt" : "ai"].label}; chuyển nhánh ở thanh phía trên để đọc hoặc biên tập.`
                  : data.has_raw
                    ? "Đã có bản gốc — bấm Dịch AI hoặc Dịch Local MT ở trên."
                    : "Chưa crawl được nội dung. Chạy bước Crawl ở trang truyện trước."}
              </p>
            </div>
          ) : (
            <ChapterBody
              paragraphs={data.translated_paras}
              editMode={editMode}
              fontSize={fontSize}
              fontFamily={readerPrefs.fontFamily}
              lineHeight={readerPrefs.lineHeight}
              notesByPara={notesByPara}
              onOpenNote={() => setNotesOpen(true)}
            />
          )}

        </div>
      )}

      {/* ── Nav cố định dưới cùng ──────────────────────────────────── */}
      <nav className="sticky bottom-0 z-30 border-t border-base-300 bg-base-100/95 backdrop-blur">
          <div
            className="relative mx-auto flex w-full items-center justify-between gap-2 px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]"
            style={{ maxWidth: `${readerPrefs.contentWidth}px` }}
          >
            <Button
              size="sm"
              variant="ghost"
              className="min-h-9 flex-1 justify-start px-2.5 sm:flex-none"
              icon={<IconChevronLeft size={16} />}
              disabled={data.prev_index === null}
              onClick={() => go(data.prev_index)}
              aria-label="Chương trước"
              title="Chương trước"
            >
              <span className="sm:hidden">Trước</span>
              <span className="hidden sm:inline">Chương trước</span>
            </Button>
            {data.has_mt_snapshot ? (
              <Button
                size="sm"
                variant="ghost"
                className="absolute left-1/2 -translate-x-1/2"
                icon={<IconRevert size={13} />}
                loading={revertEdits.isPending}
                onClick={() =>
                  revertEdits.mutate(undefined, {
                    onSuccess: () => toast("Đã khôi phục về bản dịch máy."),
                    onError: (err) =>
                      toast(err instanceof Error ? err.message : String(err), "error"),
                  })
                }
                title="Khôi phục về bản dịch máy"
              >
                <span className="hidden sm:inline">Khôi phục</span>
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              className="min-h-9 flex-1 justify-end px-2.5 sm:flex-none"
              disabled={data.next_index === null}
              onClick={() => go(data.next_index)}
              aria-label="Chương sau"
              title="Chương sau"
            >
              <span className="sm:hidden">Sau</span>
              <span className="hidden sm:inline">Chương sau</span>
              <IconChevronRight size={16} />
            </Button>
          </div>
      </nav>

      {selection ? (
        <NoteComposer
          selection={selection}
          pending={createNote.isPending}
          onCancel={() => setSelection(null)}
          onFind={(text) => {
            openFindMode(text);
            setSelection(null);
          }}
          onSubmit={(note) => {
            const s = selection;
            window.getSelection()?.removeAllRanges();
            createNote.mutate(
              { paraIndex: s.paraIndex, selectedText: s.selectedText, paraText: s.paraText, note },
              {
                onSuccess: () => {
                  setSelection(null);
                  toast("Đã thêm ghi chú.");
                },
                onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
              },
            );
          }}
        />
      ) : null}

      <BulkPreviewDialog
        open={bulkLocalMtOpen}
        onClose={() => setBulkLocalMtOpen(false)}
        slug={slug}
        action="local-mt"
        force={false}
        indexes={[...selectedChapterIndexes].sort((a, b) => a - b)}
        title={`Xem trước Local MT cho ${selectedChapterIndexes.size} chương`}
        body={
          <>
            Dịch các chương đã chọn trong TOC bằng <strong>Local MT</strong>. Chương đã có bản
            dịch Local MT sẽ được <strong>bỏ qua</strong>, không ghi đè.
          </>
        }
        confirmLabel="Xếp vào hàng đợi"
        onDone={() => {
          setSelectedChapterIndexes(new Set());
          void queryClient.invalidateQueries({ queryKey: ["chapters", slug] });
          toast("Đã xếp dịch Local MT vào hàng đợi — theo dõi ở trang Hàng đợi.");
        }}
      />
      <BulkPreviewDialog
        open={aiEditOpen}
        onClose={() => setAiEditOpen(false)}
        slug={slug}
        action="ai-edit"
        indexes={[chapterIndex]}
        title="Biên tập AI chương này"
        body={
          <>
            AI đọc bản dịch <strong>Local MT</strong> của chương {chapterIndex} và{" "}
            <strong>ghi kết quả TRỰC TIẾP vào nhánh Local MT</strong> (bản gốc dịch máy được giữ
            trong snapshot để so sánh/khôi phục). Chương có Local MT sẽ bị{" "}
            <strong>ghi đè</strong> — xem danh sách phía dưới rồi xác nhận.
          </>
        }
        confirmLabel="Xếp vào hàng đợi"
        onDone={() => {
          void queryClient.invalidateQueries({ queryKey: ["chapter", slug] });
          toast("Đã xếp biên tập AI vào hàng đợi — theo dõi ở trang Hàng đợi.");
        }}
      />
      <ChapterListDrawer
        open={chaptersOpen}
        onClose={() => setChaptersOpen(false)}
        slug={slug}
        currentIndex={chapterIndex}
        onSelect={go}
        collapsed={chaptersCollapsed}
        onToggleCollapsed={toggleChaptersCollapsed}
        mode={findMode}
        onModeChange={setFindMode}
        find={findState}
        activeFindQuery={findQuery}
        onFindChange={updateFind}
        onChangeSource={changeFindSource}
        findReady={findReady}
        onFind={runFind}
        searchState={{ loading: findLoading, error: findError ? (findError instanceof Error ? findError.message : String(findError)) : null }}
        onPreviewChapter={loadChapterPreview}
        previewState={previewState}
        onApplySelected={applyPreview}
        onApplyAll={applyAllMatches}
        onTogglePreviewItem={togglePreviewItem}
        onPreviewSelectAll={previewSelectAll}
        onPreviewSelectNone={previewSelectNone}
        searchHits={findHits ?? []}
        searchCount={searchCount}
        onClearSearch={clearSearchResults}
        selectedIndexes={selectedChapterIndexes}
        onToggleSelected={(selectedIndex) =>
          setSelectedChapterIndexes((prev) => {
            const next = new Set(prev);
            if (next.has(selectedIndex)) next.delete(selectedIndex);
            else next.add(selectedIndex);
            return next;
          })
        }
        onSelectAll={(indexes) => setSelectedChapterIndexes(new Set(indexes))}
        onClearSelected={() => setSelectedChapterIndexes(new Set())}
        onBulkLocalMt={() => setBulkLocalMtOpen(true)}
      />
      <NotesPanel
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        slug={slug}
        index={chapterIndex}
      />
    </div>
  );
}

/* ── Tiêu đề chương — bấm để sửa khi ở chế độ biên tập ──────────────── */

function ChapterTitle({
  title,
  editMode,
  onSave,
}: {
  title: string;
  editMode: boolean;
  onSave: (title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) setDraft(title);
  }, [title, editing]);

  useLayoutEffect(() => {
    if (!editing || !editorRef.current) return;
    const editor = editorRef.current;
    editor.style.height = "0px";
    editor.style.height = `${editor.scrollHeight}px`;
  }, [draft, editing]);

  if (editMode && editing) {
    return (
      <textarea
        ref={editorRef}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => {
          const value = e.target.value.trim();
          setEditing(false);
          if (value && value !== title) onSave(value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(title);
            setEditing(false);
            e.preventDefault();
          }
        }}
        className="textarea textarea-ghost mb-5 min-h-0 w-full resize-none overflow-hidden rounded-field border border-dashed border-base-300 bg-transparent px-2 py-1 text-center font-display text-2xl leading-tight outline-none focus:border-solid focus:border-primary"
        aria-label="Sửa tiêu đề chương"
      />
    );
  }

  return (
    <h1
      className={clsx(
        "mb-5 whitespace-pre-wrap text-center font-display text-2xl leading-tight",
        editMode && "cursor-text rounded-field outline-dashed outline-1 outline-base-300",
      )}
      onClick={() => editMode && setEditing(true)}
    >
      {title}
    </h1>
  );
}

/* ── Thân chương: danh sách đoạn, sửa tại chỗ + chèn đoạn mới ───────── */

function ChapterBody({
  paragraphs,
  fontSize,
  fontFamily,
  lineHeight,
  notesByPara,
  onOpenNote,
}: {
  paragraphs: string[];
  editMode: boolean;
  fontSize: number;
  fontFamily: "serif" | "sans" | "mono";
  lineHeight: number;
  notesByPara: Map<number, Note[]>;
  onOpenNote: () => void;
}) {
  return (
    <div
      className={clsx(fontFamily === "serif" && "font-read", fontFamily === "mono" && "font-mono", fontFamily === "sans" && "font-sans")}
      style={{ fontSize: `${fontSize}px`, lineHeight }}
    >
      {paragraphs.map((text, i) => (
        <p key={i} data-para-index={i} className="mb-3 text-justify">
          {renderWithNotes(text, notesByPara.get(i) ?? [], onOpenNote)}
        </p>
      ))}
    </div>
  );
}
