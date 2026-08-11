import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api, apiUrl } from "@/lib/api";
import { bytes, num, percent } from "@/lib/format";
import { decodeStrip, stripCounts } from "@/lib/strip";
import { queueKey } from "@/lib/queue";
import { useCurrentBook } from "@/lib/books";
import { aiEditDraftMessage, useAiEditDraft } from "@/lib/chapter";
import {
  DEFAULT_FILTERS,
  ebookKey,
  rowLabel,
  rowTone,
  useChapters,
  useEbook,
  type ChapterFilters,
  type ChapterRow,
} from "@/lib/ebook";
import { BulkPreviewDialog } from "@/components/chapter/BulkPreviewDialog";
import { ChapterLegend, ChapterStrip } from "@/components/ChapterStrip";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button, Spinner } from "@/components/ui/Button";
import { Dot } from "@/components/ui/Badge";
import { Checkbox, InputWithIcon, Select } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import {
  IconCaretDown,
  IconDownload,
  IconRead,
  IconSearch,
  IconSettings,
  IconSparkle,
} from "@/components/icons";

const PAGE_SIZE = 100;
const FILTERS_KEY = (slug: string) => `ebooks.${slug}.chapterFilters`;
const PAGE_KEY = (slug: string) => `ebooks.${slug}.chapterPage`;

/** Nạp bộ lọc + sắp xếp đã lưu cho truyện, hợp nhất với mặc định để khỏi vỡ schema. */
function loadFilters(slug: string): ChapterFilters {
  try {
    const raw = window.localStorage.getItem(FILTERS_KEY(slug));
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const merged = { ...DEFAULT_FILTERS };
      for (const key of Object.keys(merged) as (keyof ChapterFilters)[]) {
        const value = parsed[key];
        if (typeof value === "string") merged[key] = value;
      }
      return merged;
    }
  } catch {
    // Mất localStorage là không đáng kể — dùng mặc định.
  }
  return DEFAULT_FILTERS;
}

/** Nạp trang đã lưu cho truyện. */
function loadPage(slug: string): number {
  try {
    const raw = window.localStorage.getItem(PAGE_KEY(slug));
    return raw ? parseInt(raw, 10) : 0;
  } catch {
    return 0;
  }
}

/* ── Thanh chạy pipeline ─────────────────────────────────────────────── */

const STEPS = [
  { step: "fetch-toc", label: "Lấy mục lục" },
  { step: "crawl", label: "Crawl" },
  { step: "translate", label: "Dịch" },
  { step: "build", label: "Build EPUB" },
] as const;

function PipelineBar({ slug }: { slug: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [running, setRunning] = useState("");

  const enqueue = useMutation({
    mutationFn: (step: string) =>
      api.post<{ job_id: string }>("/api/queue/enqueue", { form: { step, ebook: slug } }),
    onMutate: (step) => setRunning(step),
    onSettled: () => setRunning(""),
    onSuccess: (_res, step) => {
      client.invalidateQueries({ queryKey: queueKey });
      toast(`Đã xếp "${step}" vào hàng đợi.`);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  return (
    <>
      {STEPS.map(({ step, label }) => (
        <Button
          key={step}
          loading={running === step}
          disabled={enqueue.isPending}
          onClick={() => enqueue.mutate(step)}
        >
          {label}
        </Button>
      ))}
    </>
  );
}

/* ── Số liệu tổng quan ───────────────────────────────────────────────── */

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-box border border-base-300 bg-base-100 px-3 py-2">
      <p className="text-[10px] tracking-[0.1em] uppercase opacity-50">{label}</p>
      <p data-numeric className="mt-0.5 text-lg leading-tight font-semibold">
        {value}
      </p>
      {hint ? <p className="text-[11px] opacity-50">{hint}</p> : null}
    </div>
  );
}

/* ── Bộ lọc bảng chương ──────────────────────────────────────────────── */

const TRISTATE = [
  { value: "any", label: "Tất cả" },
  { value: "yes", label: "Có" },
  { value: "no", label: "Không" },
];

function FilterBar({
  filters,
  onChange,
}: {
  filters: ChapterFilters;
  onChange: (next: ChapterFilters) => void;
}) {
  const set = (patch: Partial<ChapterFilters>) => onChange({ ...filters, ...patch });

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-base-300 px-3 py-2">
      <InputWithIcon
        icon={<IconSearch size={15} />}
        value={filters.search}
        onChange={(e) => set({ search: e.target.value })}
        placeholder="Tìm tiêu đề hoặc URL"
        className="w-56"
        aria-label="Tìm chương"
      />
      {(
        [
          ["filter_raw", "Bản gốc"],
          ["filter_translated", "Bản dịch"],
          ["filter_skipped", "Bỏ qua"],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="flex items-center gap-1.5 text-[11px] opacity-70">
          {label}
          <Select
            value={filters[key]}
            onChange={(e) => set({ [key]: e.target.value } as Partial<ChapterFilters>)}
            className="w-24"
            aria-label={label}
          >
            {TRISTATE.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </label>
      ))}
      <label className="flex items-center gap-1.5 text-[11px] opacity-70">
        Sắp xếp
        <Select
          value={`${filters.sort}:${filters.direction}`}
          onChange={(e) => {
            const [sort, direction] = e.target.value.split(":");
            set({ sort, direction });
          }}
          className="w-40"
          aria-label="Sắp xếp"
        >
          <option value="source:asc">Thứ tự mục lục</option>
          <option value="source:desc">Mục lục, đảo ngược</option>
          <option value="title:asc">Tiêu đề A→Z</option>
          <option value="title:desc">Tiêu đề Z→A</option>
          <option value="translated:desc">Đã dịch trước</option>
          <option value="raw:desc">Có bản gốc trước</option>
        </Select>
      </label>
    </div>
  );
}

/* ── Hành động hàng loạt ─────────────────────────────────────────────── */

/** Thao tác chạy qua các endpoint `batch/*` cũ (form-encoded, không theo nhánh). */
interface BatchAction {
  key: string;
  label: string;
  path: string;
  form?: Record<string, string>;
  destructive?: boolean;
  confirm?: (count: number) => string;
}

interface TocTitleChange {
  index: number;
  old: string;
  new: string;
  old_zh: string;
  new_zh: string;
  changed_fields: ("title" | "title_zh")[];
}

interface TocPreview {
  scanned: number;
  changed: number;
  changes: TocTitleChange[];
}

function TocTitleDiff({ label, before, after }: { label: string; before: string; after: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold tracking-[0.08em] uppercase opacity-45">{label}</p>
      <p className="break-words text-[12px] line-through opacity-50">{before || "(trống)"}</p>
      <p className="mt-0.5 break-words text-[13px] font-medium text-success">
        {after || "(trống)"}
      </p>
    </div>
  );
}

/** Nhóm "Khác" — ít dùng, gom vào menu để thanh hành động không dài ra. */
const OTHER_ACTIONS: BatchAction[] = [
  {
    key: "titles-smart",
    label: "Dịch thông minh",
    path: "batch/translate-titles",
    form: { mode: "smart" },
  },
  {
    key: "titles-fast",
    label: "Dịch nhanh",
    path: "batch/translate-titles",
    form: { mode: "fast" },
  },
  { key: "glossary", label: "Gợi ý glossary", path: "batch/suggest-glossary" },
  { key: "characters", label: "Trích nhân vật", path: "batch/extract-characters" },
  { key: "skip", label: "Bỏ qua chương", path: "batch/update-skip", form: { skip: "true" } },
  { key: "unskip", label: "Hiện lại chương", path: "batch/update-skip", form: { skip: "false" } },
  { key: "reorder", label: "Sắp xếp lại", path: "batch/reorder" },
  {
    key: "delete-translation",
    label: "Xóa bản dịch",
    path: "batch/delete-translation",
    destructive: true,
    confirm: (n) =>
      `Xóa bản dịch của ${n} chương? Bản gốc được giữ lại nên có thể dịch lại, nhưng mọi chỉnh sửa tay sẽ mất.`,
  },
  {
    key: "clean-raw",
    label: "Xóa bản gốc",
    path: "batch/clean-raw",
    destructive: true,
    confirm: (n) => `Xóa bản gốc của ${n} chương? Phải crawl lại mới có nội dung.`,
  },
];

const NORMALIZE_TOC_ACTION: BatchAction = {
  key: "clean-toc",
  label: "Chuẩn hóa TOC",
  path: "batch/clean-toc",
  confirm: (n) =>
    `Chuẩn hóa tiêu đề ${n} chương đã chọn? Thao tác sẽ bỏ tiền tố thứ tự như “3.” và ghi chú quảng cáo trong ngoặc, nhưng giữ số chương cùng các phần (上), (中), (下).`,
};

/**
 * Thanh hành động hàng loạt — CỐ ĐỊNH ở đáy màn hình.
 *
 * Trước đây thanh này `sticky` bên trong panel bảng: chọn xong ở cuối danh
 * sách 100 dòng thì phải cuộn ngược lên đầu mới bấm được. Đưa hẳn ra
 * `fixed bottom` để chọn ở đâu cũng thao tác được ngay tại chỗ.
 *
 * Ba nhóm tách hẳn nhau vì chúng KHÔNG cùng một loại việc:
 * - "Dịch": đọc bản gốc, ghi thẳng vào nhánh đã chọn → phải preview + confirm.
 * - "Biên tập AI": đọc bản dịch đang có, sinh bản nháp chờ duyệt → không ghi
 *   đè gì nên bấm một cái là xếp job luôn, không qua hộp thoại.
 * - "Khác": các thao tác phụ trợ, gom vào menu cho gọn.
 */
function BatchBar({
  slug,
  selected,
  onDone,
  onClear,
}: {
  slug: string;
  selected: number[];
  onDone: () => void;
  onClear: () => void;
}) {
  const toast = useToast();
  const [pending, setPending] = useState<BatchAction | null>(null);
  const [reorderMode, setReorderMode] = useState<"detect" | "manual" | null>(null);
  const [manualIndexes, setManualIndexes] = useState("");
  const [tocPreview, setTocPreview] = useState<TocPreview | null>(null);
  const [includeTranslatedTitle, setIncludeTranslatedTitle] = useState(false);
  const [translateAction, setTranslateAction] = useState<"translate" | "local-mt" | null>(null);
  const aiEditDraft = useAiEditDraft(slug);

  const run = useMutation({
    mutationFn: (action: BatchAction) =>
      api.post<Record<string, unknown>>(`/api/ebooks/${slug}/${action.path}`, {
        form: { indexes: selected.join(","), ...(action.form ?? {}) },
      }),
    onSuccess: (res, action) => {
      setPending(null);
      setTocPreview(null);
      onDone();
      const started = typeof res.started === "number" ? res.started : null;
      toast(
        started !== null
          ? `${action.label}: đã xếp ${started} chương vào hàng đợi.`
          : `${action.label}: xong ${selected.length} chương.`,
      );
    },
    onError: (err) => {
      setPending(null);
      toast(err instanceof Error ? err.message : String(err), "error");
    },
  });

  const previewToc = useMutation({
    mutationFn: () =>
      api.post<TocPreview>(`/api/ebooks/${slug}/${NORMALIZE_TOC_ACTION.path}`, {
        form: {
          indexes: selected.join(","),
          apply: "false",
          include_translated: String(includeTranslatedTitle),
        },
      }),
    onSuccess: (preview) => {
      if (preview.changed === 0) {
        toast("Các tiêu đề đã chọn không cần chuẩn hóa.");
        return;
      }
      setTocPreview(preview);
      setPending(NORMALIZE_TOC_ACTION);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const trigger = (action: BatchAction) => {
    if (action.key === "reorder") {
      setReorderMode("detect");
      return;
    }
    if (action.confirm) setPending(action);
    else run.mutate(action);
  };

  const runReorder = () => {
    const indexes = manualIndexes
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
      .map(Number);
    if (reorderMode === "manual" && (indexes.length === 0 || indexes.some((index) => !Number.isInteger(index)))) {
      toast("Index phải là các số nguyên, ngăn cách bằng dấu phẩy.", "error");
      return;
    }
    run.mutate({
      key: "reorder",
      label: "Sắp xếp lại",
      path: "jobs/reorder",
      form: reorderMode === "manual" ? { order: indexes.join(",") } : { order: "auto" },
    });
    setReorderMode(null);
    setManualIndexes("");
  };

  const applyTocAction: BatchAction = {
    ...NORMALIZE_TOC_ACTION,
    form: {
      apply: "true",
      include_translated: String(includeTranslatedTitle),
    },
  };

  const branchLabel = translateAction === "local-mt" ? "Local MT" : "AI";

  return (
    <>
      {/* Chừa chỗ để thanh cố định không che mất dòng cuối bảng. */}
      <div className="h-20" aria-hidden="true" />

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-base-300 bg-base-100/95 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur md:left-64">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium">
              <span data-numeric>{num(selected.length)}</span> chương
            </span>
            <Button size="sm" variant="ghost" onClick={onClear}>
              Bỏ chọn
            </Button>
          </div>

          <div className="h-8 w-px bg-base-300" aria-hidden="true" />

          <div className="flex items-center gap-1.5">
            <span className="text-[10px] tracking-[0.1em] uppercase opacity-40">Dịch</span>
            <Button size="sm" onClick={() => setTranslateAction("local-mt")}>
              Local MT
            </Button>
            <Button size="sm" onClick={() => setTranslateAction("translate")}>
              AI
            </Button>
          </div>

          <div className="h-8 w-px bg-base-300" aria-hidden="true" />

          <div className="flex items-center gap-1.5">
            <span className="text-[10px] tracking-[0.1em] uppercase opacity-40">Biên tập</span>
            <Button
              size="sm"
              variant="primary"
              icon={<IconSparkle size={13} />}
              loading={aiEditDraft.isPending}
              title="Xếp job biên tập AI cho các chương đã chọn — kết quả là bản nháp chờ duyệt"
              onClick={() =>
                aiEditDraft.mutate(selected, {
                  onSuccess: (res) => {
                    toast(aiEditDraftMessage(res));
                    onDone();
                  },
                  onError: (err) =>
                    toast(err instanceof Error ? err.message : String(err), "error"),
                })
              }
            >
              Biên tập AI
            </Button>
          </div>

          <div className="h-8 w-px bg-base-300" aria-hidden="true" />

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              loading={previewToc.isPending}
              disabled={run.isPending || previewToc.isPending}
              onClick={() => previewToc.mutate()}
            >
              Chuẩn hóa TOC
            </Button>
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] opacity-70">
              <Checkbox
                checked={includeTranslatedTitle}
                onChange={(event) => setIncludeTranslatedTitle(event.target.checked)}
              />
              Tiêu đề đã dịch
            </label>
          </div>

          <div className="ml-auto dropdown dropdown-top dropdown-end">
            <div tabIndex={0} role="button" className="btn btn-sm gap-1.5">
              Khác <IconCaretDown size={12} />
            </div>
            <ul className="dropdown-content menu menu-sm z-50 w-56 rounded-box border border-base-300 bg-base-100 shadow-lg">
              {OTHER_ACTIONS.map((action) => (
                <li key={action.key}>
                  <button
                    type="button"
                    disabled={run.isPending}
                    className={clsx(action.destructive && "text-error")}
                    onClick={() => trigger(action)}
                  >
                    {action.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <BulkPreviewDialog
        open={translateAction !== null}
        onClose={() => setTranslateAction(null)}
        slug={slug}
        action={translateAction === "local-mt" ? "local-mt" : "translate"}
        branch={translateAction === "translate" ? "ai" : ""}
        force={false}
        indexes={selected}
        title={`Dịch bằng ${branchLabel}`}
        body={
          <>
            Dịch {selected.length} chương đã chọn vào nhánh{" "}
            <strong>{branchLabel}</strong>. Chương nào đã có bản dịch trong nhánh đó sẽ được{" "}
            <strong>bỏ qua</strong>, không ghi đè.
          </>
        }
        confirmLabel="Xếp vào hàng đợi"
        onDone={onDone}
      />

      <ConfirmDialog
        open={reorderMode !== null}
        onCancel={() => {
          setReorderMode(null);
          setManualIndexes("");
        }}
        onConfirm={runReorder}
        title="Sắp xếp lại danh sách chương"
        body={
          <div className="space-y-3">
            <p>Sắp xếp toàn bộ danh sách chương theo thứ tự mới.</p>
            <div className="flex gap-2">
              <Button size="sm" variant={reorderMode === "detect" ? "primary" : "ghost"} onClick={() => setReorderMode("detect")}>Detect tên chương</Button>
              <Button size="sm" variant={reorderMode === "manual" ? "primary" : "ghost"} onClick={() => setReorderMode("manual")}>Nhập index thủ công</Button>
            </div>
            {reorderMode === "manual" ? (
              <InputWithIcon
                icon={<span className="text-xs opacity-50">#</span>}
                value={manualIndexes}
                onChange={(event) => setManualIndexes(event.target.value)}
                placeholder="Ví dụ: 3, 1, 2, 4"
                aria-label="Thứ tự index chương"
              />
            ) : null}
          </div>
        }
        confirmLabel="Sắp xếp"
        pending={run.isPending}
      />

      <ConfirmDialog
        open={pending !== null}
        onCancel={() => {
          setPending(null);
          setTocPreview(null);
        }}
        onConfirm={() => pending && run.mutate(pending.key === "clean-toc" ? applyTocAction : pending)}
        title={pending?.label ?? ""}
        body={
          pending?.key === "clean-toc" && tocPreview ? (
            <div className="space-y-3">
              <p>
                Tìm thấy <strong data-numeric>{num(tocPreview.changed)}</strong> tiêu đề cần chuẩn
                hóa trong <span data-numeric>{num(tocPreview.scanned)}</span> chương đã quét.
              </p>
              <div>
                <p className="mb-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-50">
                  Xem trước {Math.min(6, tocPreview.changes.length)} thay đổi
                </p>
                <ol className="scroll-slim max-h-72 space-y-2 overflow-y-auto rounded-box border border-base-300 bg-base-200/40 p-3">
                  {tocPreview.changes.slice(0, 6).map((change) => (
                    <li key={change.index} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-2">
                      <span data-numeric className="pt-0.5 text-right text-[11px] opacity-40">
                        {change.index}
                      </span>
                      <div className="min-w-0 space-y-2">
                        {change.changed_fields.includes("title_zh") ? (
                          <TocTitleDiff label="Gốc" before={change.old_zh} after={change.new_zh} />
                        ) : null}
                        {change.changed_fields.includes("title") ? (
                          <TocTitleDiff label="Đã dịch" before={change.old} after={change.new} />
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
                {tocPreview.changed > 6 ? (
                  <p className="mt-1.5 text-[11px] opacity-50">
                    Và <span data-numeric>{num(tocPreview.changed - 6)}</span> tiêu đề khác.
                  </p>
                ) : null}
              </div>
              <p className="opacity-70">
                Các phần (上), (中), (下) được giữ lại. Chỉ ghi dữ liệu sau khi xác nhận.
              </p>
            </div>
          ) : (
            pending?.confirm?.(selected.length) ?? ""
          )
        }
        confirmLabel={pending?.label}
        destructive={pending?.destructive}
        pending={run.isPending}
      />
    </>
  );
}

/* ── Bảng chương ─────────────────────────────────────────────────────── */

function ChapterTableRow({
  slug,
  row,
  checked,
  onSelect,
}: {
  slug: string;
  row: ChapterRow;
  checked: boolean;
  onSelect: (index: number, event: ReactMouseEvent, source: "row" | "checkbox") => void;
}) {
  return (
    <tr
      className={clsx(
        "cursor-default border-b border-base-300 transition-colors last:border-b-0 hover:bg-base-200/45",
        checked && "bg-warning/5 hover:bg-warning/10",
      )}
      aria-selected={checked}
      onClick={(event) => {
        const target = event.target as HTMLElement;
        if (target.closest("a, button, input, label, select, textarea")) return;
        onSelect(row.index, event, "row");
      }}
    >
      <td className="w-9 px-2 py-1">
        <Checkbox
          checked={checked}
          onClick={(event) => onSelect(row.index, event, "checkbox")}
          onChange={() => undefined}
          aria-label={`Chọn chương ${row.index}`}
        />
      </td>
      <td data-numeric className="w-14 px-2 py-1 text-xs opacity-60">
        {row.index}
      </td>
      <td className="px-2 py-1">
        <Link
          to={`/ebooks/${slug}/chapters/${row.index}`}
          className={clsx("text-[13px] hover:text-primary", row.skipped && "line-through opacity-50")}
        >
          {row.visible_title}
        </Link>
        {row.duplicate_of ? (
          <span data-numeric className="ml-2 text-[11px] text-error">
            trùng #{row.duplicate_of}
          </span>
        ) : null}
      </td>
      <td className="w-32 px-2 py-1">
        <span className="flex items-center gap-1.5 text-[11px] opacity-70">
          <Dot tone={rowTone(row)} />
          {rowLabel(row)}
        </span>
      </td>
      <td data-numeric className="w-20 px-2 py-1 text-right text-xs opacity-60">
        {row.zh_char_count ? num(row.zh_char_count) : "—"}
      </td>
      <td data-numeric className="w-20 px-2 py-1 text-right text-xs opacity-60">
        {row.word_count ? num(row.word_count) : "—"}
      </td>
      <td className="w-24 px-2 py-1 text-right">
        <Link
          to={`/ebooks/${slug}/chapters/${row.index}`}
          className="text-[11px] opacity-60 hover:text-primary hover:opacity-100"
        >
          Đọc
        </Link>
      </td>
    </tr>
  );
}

/* ── Trang ───────────────────────────────────────────────────────────── */

export function EbookPage() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [, selectBook] = useCurrentBook();
  const [filters, setFilters] = useState<ChapterFilters>(() => loadFilters(slug));
  const [offset, setOffset] = useState(() => loadPage(slug));
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [lastToggled, setLastToggled] = useState<number | null>(null);

  const { data: book, isPending, error } = useEbook(slug);
  const { data: page, isFetching } = useChapters(slug, filters, offset, PAGE_SIZE);

  const isNonContinuous = useMemo(() => {
    if (!page?.rows.length) return false;
    const indices = page.rows.map(r => r.index).sort((a, b) => a - b);
    for (let i = 0; i < indices.length - 1; i++) {
        if (indices[i+1] !== indices[i] + 1) return true;
    }
    return false;
  }, [page?.rows]);

  // Mở thẳng trang truyện cũng là "đang làm truyện này" — thanh điều hướng
  // phải theo, nếu không người dùng thấy hai truyện khác nhau trên cùng màn.
  useEffect(() => {
    if (slug) selectBook(slug);
  }, [slug, selectBook]);

  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
    setLastToggled(null);
  }, [filters]);

  // Giữ bộ lọc + sắp xếp + trang qua các lần vào lại trang truyện này.
  useEffect(() => {
    try {
      window.localStorage.setItem(FILTERS_KEY(slug), JSON.stringify(filters));
      window.localStorage.setItem(PAGE_KEY(slug), String(offset));
    } catch {
      // Quota đầy hoặc ẩn danh — bỏ qua, chỉ mất lần lưu này.
    }
  }, [slug, filters, offset]);

  const states = useMemo(() => decodeStrip(book?.strip ?? ""), [book?.strip]);
  const counts = useMemo(() => stripCounts(book?.counts ?? {}), [book?.counts]);
  const rows = page?.rows ?? [];

  const selectRow = (
    index: number,
    event: ReactMouseEvent,
    source: "row" | "checkbox",
  ) => {
    setSelected((prev) => {
      const additive = event.ctrlKey || event.metaKey || source === "checkbox";
      const next = additive ? new Set(prev) : new Set<number>();
      if (event.shiftKey && lastToggled !== null) {
        const visible = rows.map((row) => row.index);
        const from = visible.indexOf(lastToggled);
        const to = visible.indexOf(index);
        if (from !== -1 && to !== -1) {
          const [lo, hi] = from < to ? [from, to] : [to, from];
          for (let i = lo; i <= hi; i++) next.add(visible[i]);
          return next;
        }
      }
      if (additive && prev.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
    setLastToggled(index);
  };

  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.index));
  const refresh = () => {
    client.invalidateQueries({ queryKey: ebookKey(slug) });
    client.invalidateQueries({ queryKey: ["chapters", slug] });
    client.invalidateQueries({ queryKey: queueKey });
    setSelected(new Set());
    setLastToggled(null);
  };

  if (isPending) {
    return (
      <Page title="Đang tải">
        <div className="flex items-center justify-center gap-2 py-20 text-sm opacity-60">
          <Spinner /> Đang đọc dữ liệu truyện
        </div>
      </Page>
    );
  }

  if (error || !book) {
    return (
      <Page title="Không mở được truyện">
        <Panel>
          <EmptyState
            title="Không đọc được truyện này"
            hint={error instanceof Error ? error.message : String(error)}
          />
        </Panel>
      </Page>
    );
  }

  return (
    <Page
      title={book.title || slug}
      hint={
        <>
          <span data-numeric>{slug}</span>
          {book.author ? <span> · {book.author}</span> : null}
          <span> · {book.translate_type}</span>
          {book.translate_model ? <span data-numeric> {book.translate_model}</span> : null}
          <span> · crawl {book.crawl_mode}</span>
        </>
      }
      actions={
        <>
          <PipelineBar slug={slug} />
          <Button
            variant="primary"
            icon={<IconRead size={15} />}
            onClick={() => navigate(`/ebooks/${slug}/chapters`)}
          >
            Đọc
          </Button>
          <Button
            variant="ghost"
            icon={<IconSettings size={15} />}
            onClick={() => navigate(`/ebooks/${slug}/settings`)}
            aria-label="Cài đặt truyện"
          />
        </>
      }
    >
      {book.active_jobs.length > 0 ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-box border border-warning/40 bg-warning/10 px-3 py-2 text-[13px]">
          <Dot tone="gold" pulse />
          Đang chạy: {book.active_jobs.map((j) => j.label).join(", ")}
        </div>
      ) : null}

      {isNonContinuous ? (
        <div className="mb-3 flex items-center gap-2 rounded-box border border-error/40 bg-error/10 px-3 py-2 text-[13px]">
          <Dot tone="red" />
          Danh sách chương trên trang hiện tại không liên tục.
        </div>
      ) : null}

      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-5">
        <Stat label="Chương" value={num(book.total)} hint={book.has_manifest ? undefined : "chưa có mục lục"} />
        <Stat
          label="Có bản gốc"
          value={num(book.raw_count)}
          hint={`${percent(book.raw_count, book.total)}%`}
        />
        <Stat
          label="Đã dịch"
          value={num(book.translated_count)}
          hint={`${percent(book.translated_count, book.total)}%`}
        />
        <Stat
          label="EPUB"
          value={book.epub_exists ? bytes(book.epub_size) : "—"}
          hint={book.epub_exists ? "đã build" : "chưa build"}
        />
        <Stat
          label="Chi phí AI"
          value={book.cost_summary ? `$${book.cost_summary.total_cost_usd.toFixed(2)}` : "—"}
          hint={book.cost_summary ? `${num(book.cost_summary.chapter_count)} chương` : undefined}
        />
      </div>

      {book.total > 0 ? (
        <Panel className="mb-4 p-3">
          <ChapterStrip states={states} height={30} />
          <div className="mt-2">
            <ChapterLegend counts={counts} />
          </div>
        </Panel>
      ) : null}

      <Panel className="overflow-hidden">
        <PanelHeader
          title="Chương"
          hint={
            page ? (
              <>
                <span data-numeric>{num(page.matched)}</span> chương khớp bộ lọc
                {page.matched !== page.total ? (
                  <>
                    {" "}
                    trên tổng <span data-numeric>{num(page.total)}</span>
                  </>
                ) : null}
              </>
            ) : undefined
          }
          actions={
            selected.size === 0 && page && page.matched > 0 ? (
              <Button size="sm" onClick={() => setSelected(new Set(page.indexes))}>
                Chọn tất cả {num(page.matched)} chương khớp
              </Button>
            ) : null
          }
        />

        <FilterBar filters={filters} onChange={setFilters} />

        {rows.length === 0 ? (
          <EmptyState
            title={book.has_manifest ? "Không có chương nào khớp" : "Chưa có mục lục"}
            hint={
              book.has_manifest
                ? "Nới bộ lọc hoặc xóa từ khóa tìm kiếm."
                : "Chạy bước Lấy mục lục để nạp danh sách chương từ nguồn."
            }
          />
        ) : (
          <div className={clsx("overflow-x-auto", isFetching && "opacity-60")}>
            <table className="w-full min-w-[52rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-base-300 bg-base-200/60">
                  <th className="w-9 px-2 py-1.5">
                    <Checkbox
                      checked={allOnPage}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          rows.forEach((r) =>
                            allOnPage ? next.delete(r.index) : next.add(r.index),
                          );
                          return next;
                        })
                      }
                      aria-label="Chọn tất cả chương trên trang"
                    />
                  </th>
                  {["#", "Tiêu đề", "Trạng thái", "Chữ Hán", "Từ", ""].map((h, i) => (
                    <th
                      key={h || i}
                      className={clsx(
                        "px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40",
                        (h === "Chữ Hán" || h === "Từ") && "text-right",
                      )}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ChapterTableRow
                    key={row.index}
                    slug={slug}
                    row={row}
                    checked={selected.has(row.index)}
                    onSelect={selectRow}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {page && page.matched > PAGE_SIZE ? (
          <div className="flex items-center justify-between border-t border-base-300 px-3 py-2">
            <span data-numeric className="text-[11px] opacity-60">
              {num(offset + 1)}–{num(Math.min(offset + PAGE_SIZE, page.matched))} /{" "}
              {num(page.matched)}
            </span>
            <div className="flex gap-1.5">
              <Button
                size="sm"
                disabled={offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - PAGE_SIZE));
                  setLastToggled(null);
                }}
              >
                Trước
              </Button>
              <Button
                size="sm"
                disabled={offset + PAGE_SIZE >= page.matched}
                onClick={() => {
                  setOffset(offset + PAGE_SIZE);
                  setLastToggled(null);
                }}
              >
                Sau
              </Button>
            </div>
          </div>
        ) : null}
      </Panel>

      <p className="mt-3 text-xs opacity-50">
        Click vùng trống để chọn một dòng; giữ Ctrl/Cmd để thêm hoặc bỏ từng dòng, Shift để chọn cả dải.{" "}
        <a
          href={apiUrl(`/ebooks/${slug}/toc.csv`)}
          className="inline-flex items-center gap-1 hover:text-primary"
        >
          <IconDownload size={11} /> Xuất CSV mục lục
        </a>{" "}
        để sửa tiêu đề bằng bảng tính.
      </p>

      {selected.size > 0 ? (
        <BatchBar
          slug={slug}
          selected={[...selected]}
          onDone={refresh}
           onClear={() => {
             setSelected(new Set());
             setLastToggled(null);
           }}

        />
      ) : null}
    </Page>
  );
}
