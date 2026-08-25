import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { Page } from "@/app/Shell";
import { api, apiUrl } from "@/lib/api";
import { bytes, num, percent } from "@/lib/format";
import { decodeStrip, stripCounts } from "@/lib/strip";
import { queueKey } from "@/lib/queue";
import {
  AUTOMATION_STEP_META,
  automationStepName,
  type Automation,
  type AutomationOverview,
} from "@/lib/automation";
import { useCurrentBook } from "@/lib/books";
import {
  CHAPTER_FILTERS_KEY,
  chapterOrdinal,
  ebookKey,
  loadChapterFilters,
  rowLabel,
  rowTone,
  rowWarnings,
  useChapters,
  useEbook,
  type ChapterFilters,
  type ChapterRow,
} from "@/lib/ebook";
import { BulkPreviewDialog } from "@/components/chapter/BulkPreviewDialog";
import { ChapterLegend, ChapterStrip } from "@/components/ChapterStrip";
import { Panel, PanelHeader, EmptyState } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { Loading, SkeletonTable } from "@/components/ui/Loading";
import { Dot } from "@/components/ui/Badge";
import { Checkbox, Input, InputWithIcon, Select, Textarea } from "@/components/ui/Field";
import { ConfirmDialog, Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import {
  IconCaretDown,
  IconChat,
  IconDownload,
  IconPlay,
  IconRead,
  IconSearch,
  IconSettings,
  IconSparkle,
} from "@/components/icons";

/** Backend chặn `limit` ở 500 (`GET /api/ui/ebooks/{slug}/chapters`) — đừng
    đưa lựa chọn lớn hơn vào đây, người dùng sẽ thấy số hiển thị không khớp. */
const PAGE_SIZES = [25, 50, 100, 200, 500] as const;
const DEFAULT_PAGE_SIZE = 100;
const PAGE_KEY = (slug: string) => `ebooks.${slug}.chapterPage`;
const PAGE_SIZE_KEY = (slug: string) => `ebooks.${slug}.chapterPageSize`;

/** Nạp trang đã lưu cho truyện. */
function loadPage(slug: string): number {
  try {
    const raw = window.localStorage.getItem(PAGE_KEY(slug));
    return raw ? parseInt(raw, 10) : 0;
  } catch {
    return 0;
  }
}

/** Nạp cỡ trang đã lưu, bỏ qua giá trị lạ (bản cũ, người dùng sửa tay). */
function loadPageSize(slug: string): number {
  try {
    const raw = window.localStorage.getItem(PAGE_SIZE_KEY(slug));
    const value = raw ? parseInt(raw, 10) : NaN;
    return (PAGE_SIZES as readonly number[]).includes(value) ? value : DEFAULT_PAGE_SIZE;
  } catch {
    return DEFAULT_PAGE_SIZE;
  }
}

/** Giá trị sau khi ngừng thay đổi `delay` ms — dùng cho ô tìm kiếm để mỗi
    lần gõ không bắn một request danh sách chương mới lên server. */
function useDebouncedValue(value: string, delay = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/* ── Thanh chạy pipeline ─────────────────────────────────────────────── */

const STEPS = [
  { step: "fetch-toc", label: "Lấy mục lục" },
  { step: "crawl", label: "Crawl" },
  { step: "build", label: "Build EPUB" },
] as const;

function PipelineBar({ slug, epubExists }: { slug: string; epubExists: boolean }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [running, setRunning] = useState("");
  const [automationOpen, setAutomationOpen] = useState(false);
  const [overview, setOverview] = useState<AutomationOverview | null>(null);
  const [selectedAutomationId, setSelectedAutomationId] = useState("");
  const [selectedSteps, setSelectedSteps] = useState<string[]>([]);
  const [crawlWorkers, setCrawlWorkers] = useState("4");
  const [translateWorkers, setTranslateWorkers] = useState("4");

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

  const loadAutomations = useMutation({
    mutationFn: () => api.get<AutomationOverview>("/api/ui/automation"),
    onSuccess: (data) => {
      setOverview(data);
      const first = data.automations.find((automation) => automation.ebook === slug);
      setSelectedAutomationId(first?.id ?? "");
      setSelectedSteps(data.steps);
      setCrawlWorkers("4");
      setTranslateWorkers("4");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const runAutomation = useMutation({
    mutationFn: (id: string) =>
      api.post<{ ok: boolean; job_id: string }>(`/api/ui/automation/${id}/run-now`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queueKey });
      client.invalidateQueries({ queryKey: ["automation"] });
      setAutomationOpen(false);
      toast("Đã đưa workflow tự động vào hàng đợi.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const createAndRun = useMutation({
    mutationFn: async () => {
      const crawl = Number(crawlWorkers);
      const translate = Number(translateWorkers);
      if (!selectedSteps.length) throw new Error("Cần chọn ít nhất một bước.");
      if (!Number.isInteger(crawl) || crawl < 1 || crawl > 64 || !Number.isInteger(translate) || translate < 1 || translate > 64) {
        throw new Error("Số luồng phải là số nguyên từ 1 đến 64.");
      }
      const created = await api.post<Automation>("/api/ui/automation", {
        body: {
          ebook: slug,
          steps: selectedSteps,
          schedule: "manual",
          crawl_workers: crawl,
          translate_workers: translate,
        },
      });
      try {
        await api.post<{ ok: boolean; job_id: string }>(`/api/ui/automation/${created.id}/run-now`);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        throw new Error(`Đã tạo workflow nhưng chưa chạy được: ${reason}`);
      }
      return created;
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queueKey });
      client.invalidateQueries({ queryKey: ["automation"] });
      setAutomationOpen(false);
      toast("Đã tạo workflow thủ công và đưa vào hàng đợi.");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const openAutomation = () => {
    setOverview(null);
    loadAutomations.reset();
    setAutomationOpen(true);
    loadAutomations.mutate();
  };
  const bookAutomations = overview?.automations.filter((automation) => automation.ebook === slug) ?? [];
  const selectedAutomation = bookAutomations.find((automation) => automation.id === selectedAutomationId)
    ?? bookAutomations[0];
  const automationPending = runAutomation.isPending || createAndRun.isPending;

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
      <Button icon={<IconPlay size={14} />} onClick={openAutomation}>
        Tự động
      </Button>
      <Button
        icon={<IconDownload size={14} />}
        disabled={!epubExists}
        title={epubExists ? "Tải tệp EPUB đã build" : "Chưa có EPUB — hãy chạy Build EPUB trước"}
        onClick={() => { window.location.href = apiUrl(`/ebooks/${slug}/download`); }}
      >
        Tải EPUB
      </Button>

      <Modal
        open={automationOpen}
        onClose={() => !automationPending && setAutomationOpen(false)}
        title={bookAutomations.length ? "Xem trước workflow tự động" : "Tạo workflow tự động"}
        wide
        footer={
          <>
            <Button onClick={() => setAutomationOpen(false)} disabled={automationPending}>Hủy</Button>
            {selectedAutomation ? (
              <>
                <Button onClick={() => navigate("/automation")} disabled={automationPending}>Mở trang Tự động</Button>
                <Button
                  variant="primary"
                  icon={<IconPlay size={14} />}
                  loading={runAutomation.isPending}
                  onClick={() => runAutomation.mutate(selectedAutomation.id)}
                >
                  Chạy workflow
                </Button>
              </>
            ) : overview ? (
              <Button
                variant="primary"
                icon={<IconPlay size={14} />}
                loading={createAndRun.isPending}
                onClick={() => createAndRun.mutate()}
              >
                Tạo và chạy
              </Button>
            ) : null}
          </>
        }
      >
        {loadAutomations.isPending ? (
          <Loading label="Đang đọc workflow" />
        ) : loadAutomations.isError ? (
          <EmptyState
            title="Không đọc được workflow"
            hint={loadAutomations.error instanceof Error ? loadAutomations.error.message : String(loadAutomations.error)}
            action={<Button onClick={() => loadAutomations.mutate()}>Thử lại</Button>}
          />
        ) : !overview ? null : selectedAutomation ? (
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
            <div className="min-w-0">
              {bookAutomations.length > 1 ? (
                <label className="mb-4 block text-xs">
                  <span className="mb-1 block font-medium">Workflow</span>
                  <Select
                    value={selectedAutomation.id}
                    onChange={(event) => setSelectedAutomationId(event.target.value)}
                    className="w-full"
                  >
                    {bookAutomations.map((automation, index) => (
                      <option key={automation.id} value={automation.id}>
                        Workflow {index + 1} · {automation.steps.length} bước · {automation.schedule === "manual" ? "thủ công" : automation.schedule}
                      </option>
                    ))}
                  </Select>
                </label>
              ) : null}
              <ol className="overflow-hidden rounded-field border border-base-300">
                {selectedAutomation.steps.map((step, index) => (
                  <li key={`${step}-${index}`} className="flex gap-3 border-b border-base-300 px-3 py-2.5 last:border-b-0">
                    <span data-numeric className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{index + 1}</span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-semibold">{automationStepName(step)}</span>
                      <span className="block text-[11px] opacity-55">{AUTOMATION_STEP_META[step]?.description}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
            <dl className="grid h-fit grid-cols-[auto_1fr] gap-x-3 gap-y-2 rounded-field border border-base-300 bg-base-200/35 p-3 text-xs">
              <dt className="opacity-55">Lịch</dt><dd className="text-right font-medium">{selectedAutomation.schedule === "manual" ? "Chỉ thủ công" : selectedAutomation.schedule}</dd>
              <dt className="opacity-55">Trạng thái</dt><dd className="text-right font-medium">{selectedAutomation.enabled ? "Đang bật" : "Đã tắt lịch"}</dd>
              <dt className="opacity-55">Luồng cào</dt><dd data-numeric className="text-right font-medium">{selectedAutomation.crawl_workers}</dd>
              <dt className="opacity-55">Luồng dịch</dt><dd data-numeric className="text-right font-medium">{selectedAutomation.translate_workers}</dd>
              <dt className="opacity-55">Lần cuối</dt><dd data-numeric className="truncate text-right font-medium" title={selectedAutomation.last_run_at}>{selectedAutomation.last_run_at || "Chưa chạy"}</dd>
              {selectedAutomation.last_run_error ? <><dt className="text-error">Lỗi gần nhất</dt><dd className="break-words text-right text-error">{selectedAutomation.last_run_error}</dd></> : null}
            </dl>
          </div>
        ) : (
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
            <div>
              <p className="mb-3 text-xs opacity-65">Truyện chưa có workflow. Chọn các bước sẽ được lưu theo chế độ chạy thủ công rồi chạy ngay một lần.</p>
              <div className="overflow-hidden rounded-field border border-base-300">
                {overview.steps.map((step) => (
                  <label key={step} className="flex cursor-pointer items-center gap-3 border-b border-base-300 px-3 py-2.5 last:border-b-0 hover:bg-base-200/40">
                    <Checkbox
                      checked={selectedSteps.includes(step)}
                      onChange={() => setSelectedSteps((current) => current.includes(step) ? current.filter((item) => item !== step) : [...current, step])}
                    />
                    <span className="min-w-0">
                      <span className="block text-[13px] font-semibold">{automationStepName(step)}</span>
                      <span className="block text-[11px] opacity-55">{AUTOMATION_STEP_META[step]?.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div className="h-fit space-y-3 rounded-field border border-base-300 bg-base-200/35 p-3">
              <p className="text-xs font-semibold">Tài nguyên</p>
              <label className="block text-xs">
                <span className="mb-1 block opacity-65">Luồng cào</span>
                <Input value={crawlWorkers} onChange={(event) => setCrawlWorkers(event.target.value)} type="number" min={1} max={64} />
              </label>
              <label className="block text-xs">
                <span className="mb-1 block opacity-65">Luồng LLM dịch</span>
                <Input value={translateWorkers} onChange={(event) => setTranslateWorkers(event.target.value)} type="number" min={1} max={64} />
              </label>
              <p className="text-[11px] leading-relaxed opacity-55">Lịch mặc định: chỉ chạy thủ công. Có thể đổi cron tại trang Tự động.</p>
            </div>
          </div>
        )}
      </Modal>
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

/** Tri-state cho lỗi tiêu đề — "Có/Không" ở đây nghĩa là "có lỗi/không lỗi",
    đọc ngược so với các cột dữ liệu nên phải đặt chữ khác. */
const TITLE_ERROR_STATES = [
  { value: "any", label: "Tất cả" },
  { value: "yes", label: "Sai mẫu" },
  { value: "no", label: "Đúng mẫu" },
];

/**
 * Ba bộ lọc nhánh dịch tách rời nhau vì chúng trả lời ba câu hỏi khác nhau:
 * "Bản dịch" xét nhánh ĐANG ACTIVE (thứ đi vào EPUB/Reader), còn "Local MT" và
 * "AI" xét dữ liệu từng nhánh. Gộp lại như trước thì không lọc được "đã có MT
 * nhưng chưa có bản AI" — đúng tập chương cần xếp job dịch AI.
 */
const FILTER_SELECTS = [
  { key: "filter_raw", label: "Bản gốc", options: TRISTATE, width: "w-24" },
  { key: "filter_translated", label: "Bản dịch", options: TRISTATE, width: "w-24" },
  { key: "filter_local_mt", label: "Local MT", options: TRISTATE, width: "w-24" },
  { key: "filter_ai", label: "AI", options: TRISTATE, width: "w-24" },
  { key: "filter_title_error", label: "Tiêu đề", options: TITLE_ERROR_STATES, width: "w-28" },
  { key: "filter_skipped", label: "Bỏ qua", options: TRISTATE, width: "w-24" },
] as const satisfies readonly {
  key: keyof ChapterFilters;
  label: string;
  options: { value: string; label: string }[];
  width: string;
}[];

function FilterBar({
  filters,
  onChange,
}: {
  filters: ChapterFilters;
  onChange: (next: ChapterFilters) => void;
}) {
  const set = (patch: Partial<ChapterFilters>) => onChange({ ...filters, ...patch });
  const activeCount = FILTER_SELECTS.filter(({ key }) => filters[key] !== "any").length;

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
      {FILTER_SELECTS.map(({ key, label, options, width }) => (
        <label
          key={key}
          className={clsx(
            "flex items-center gap-1.5 text-[11px]",
            filters[key] === "any" ? "opacity-70" : "font-medium opacity-100",
          )}
        >
          {label}
          <Select
            value={filters[key]}
            onChange={(e) => set({ [key]: e.target.value } as Partial<ChapterFilters>)}
            className={clsx(width, filters[key] !== "any" && "border-primary/60")}
            aria-label={label}
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </label>
      ))}
      {activeCount > 0 ? (
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            onChange({
              ...filters,
              ...Object.fromEntries(FILTER_SELECTS.map(({ key }) => [key, "any"])),
            })
          }
        >
          Xóa {activeCount} bộ lọc
        </Button>
      ) : null}
      <label className="flex cursor-pointer items-center gap-1.5 text-[11px] opacity-70">
        <Checkbox
          checked={filters.show_zh_title}
          onChange={(event) => set({ show_zh_title: event.target.checked })}
        />
        Hiển thị zh_title
      </label>
      <label className="flex items-center gap-1.5 text-[11px] opacity-70">
        Sắp xếp
        <Select
          value={`${filters.sort}:${filters.direction}`}
          onChange={(e) => {
            const [sort, direction] = e.target.value.split(":");
            set({ sort, direction });
          }}
          className="w-44"
          aria-label="Sắp xếp"
        >
          <option value="source:asc">Thứ tự mục lục</option>
          <option value="source:desc">Mục lục, đảo ngược</option>
          <option value="title:asc">Tiêu đề A→Z</option>
          <option value="title:desc">Tiêu đề Z→A</option>
          <option value="translated:desc">Đã dịch trước</option>
          <option value="raw:desc">Có bản gốc trước</option>
          <option value="zh_chars:desc">Bản gốc: nhiều chữ trước</option>
          <option value="zh_chars:asc">Bản gốc: ít chữ trước</option>
          <option value="words:desc">Bản dịch: nhiều từ trước</option>
          <option value="words:asc">Bản dịch: ít từ trước</option>
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
  /** Thay đổi tiêu đề theo NHÁNH dịch (Local MT/AI) — backend dọn song song
      manifest, mỗi nhánh có diff riêng cho title/title_zh. */
  branches?: Record<string, Record<string, [string, string]>>;
}

interface TocPreview {
  scanned: number;
  changed: number;
  changes: TocTitleChange[];
}

interface ReaderPublishPreview {
  new: number;
  edited: number;
  unchanged: number;
  skipped: number;
}

/** Một phép đảo vị trí khi sắp xếp chương — from/to là vị trí 1-based trước/sau. */
interface ReorderChange {
  index: number;
  from: number;
  to: number;
}

interface ReorderResult {
  mode: "auto" | "manual";
  total: number;
  moved: number;
  changes: ReorderChange[];
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
    label: "Dịch tiêu đề thông minh",
    path: "batch/translate-titles",
    form: { mode: "smart" },
  },
  {
    key: "titles-fast",
    label: "Dịch tiêu đề nhanh",
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
    `Chuẩn hóa tiêu đề ${n} chương đã chọn? Mặc định chỉ dọn tiêu đề đã dịch và các nhánh Local MT/AI; tiêu đề gốc được giữ nguyên để lần cập nhật mục lục sau không nhận nhầm thành chương mới.`,
};

/** Crawl chỉ tải chương CHƯA có raw; force tải LẠI tất cả (raw cũ bị ghi đè,
    bản dịch giữ nguyên). Cả hai chạy qua `batch/crawl` — job nền, có thể dừng. */
const CRAWL_ACTION: BatchAction = {
  key: "crawl",
  label: "Crawl",
  path: "batch/crawl",
  form: { force: "false" },
  confirm: (n) =>
    `Crawl nội dung ${n} chương đã chọn? Chương nào chưa có bản gốc mới được tải.`,
};

const CRAWL_FORCE_ACTION: BatchAction = {
  key: "crawl-force",
  label: "Crawl lại (force)",
  path: "batch/crawl",
  form: { force: "true" },
  destructive: true,
  confirm: (n) =>
    `Tải LẠI bản gốc của ${n} chương đã chọn? Raw cũ bị ghi đè — dùng khi chương bị crawl lỗi hoặc nguồn vừa sửa nội dung. Bản dịch giữ nguyên.`,
};

type WebChatProfile = "raw-config" | "raw-static" | "translated" | "glossary";

const WEB_CHAT_PROFILES: {
  key: WebChatProfile;
  label: string;
  source: string;
  promptProfile?: string;
  hint: string;
}[] = [
  {
    key: "raw-config",
    label: "Dịch — Config truyện",
    source: "raw",
    promptProfile: "config",
    hint: "Prompt dịch render từ config truyện (giống bản dịch AI backend).",
  },
  {
    key: "raw-static",
    label: "Dịch — Prompt mặc định",
    source: "raw",
    promptProfile: "static",
    hint: "Prompt TRANSLATE_PROMPT tĩnh có sẵn của hệ thống.",
  },
  {
    key: "translated",
    label: "Biên tập bản dịch",
    source: "translated",
    hint: "Prompt EDIT_PROMPT — biên tập lại bản dịch đã có.",
  },
  {
    key: "glossary",
    label: "Dọn glossary",
    source: "glossary",
    hint: "Chỉ xuất các mục glossary detect trong chương đã chọn.",
  },
];

interface WebChatPreview {
  mode: "preview";
  chapters: { index: number; changed: boolean; title_changed: boolean }[];
  titles_changed: number[];
  missing: number[];
  unknown: number[];
  extra: number[];
  glossary_new: Record<string, string>;
}

interface WebChatExportResult {
  text: string;
  skipped: number[];
  total: number;
  source: string;
  count?: number;
}

/**
 * Hộp thoại "Web chat" — xuất/nhập dữ liệu cho AI ngoài app.
 *
 * Tab Xuất: chọn prompt profile, gọi export rồi hiện khối Markdown để dán vào
 * AI web chat. Tab Nhập: dán kết quả AI về, preview rồi xác nhận (chương qua
 * batch/import, riêng profile "Dọn glossary" qua /glossary/import).
 */
function WebChatDialog({
  open,
  onClose,
  slug,
  indexes,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  indexes: number[];
  onDone: () => void;
}) {
  const toast = useToast();
  const [tab, setTab] = useState<"export" | "import">("export");
  const [profile, setProfile] = useState<WebChatProfile>("raw-config");
  const [importText, setImportText] = useState("");
  const [preview, setPreview] = useState<WebChatPreview | null>(null);
  const [importError, setImportError] = useState("");

  const current = WEB_CHAT_PROFILES.find((p) => p.key === profile)!;

  const exportMut = useMutation({
    mutationFn: (p: WebChatProfile) => {
      const cfg = WEB_CHAT_PROFILES.find((x) => x.key === p)!;
      return api.post<WebChatExportResult>(`/api/ebooks/${slug}/batch/export`, {
        form: {
          indexes: indexes.join(","),
          source: cfg.source,
          ...(cfg.promptProfile ? { prompt_profile: cfg.promptProfile } : {}),
        },
      });
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const importMut = useMutation({
    mutationFn: async (mode: "preview" | "confirm") => {
      if (profile === "glossary") {
        return api.post<{ added: number; updated: number }>(`/api/ebooks/${slug}/glossary/import`, {
          form: { text: importText },
        });
      }
      return api.post<WebChatPreview>(
        `/api/ebooks/${slug}/batch/import`,
        { form: { text: importText, indexes: indexes.join(","), mode } },
      );
    },
    onSuccess: (res, mode) => {
      if (profile === "glossary") {
        const g = res as { added: number; updated: number };
        toast(`Đã nhập glossary: ${g.added} mới, ${g.updated} cập nhật.`);
        onDone();
        onClose();
        return;
      }
      if (mode === "preview") {
        setPreview(res as WebChatPreview);
        return;
      }
      const done = res as WebChatPreview & { written: number[]; glossary_added: number };
      toast(`Đã ghi ${done.written.length} chương, thêm ${done.glossary_added} mục glossary.`);
      onDone();
      onClose();
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err);
      setImportError(message);
      toast(message, "error");
    },
  });

  // Xuất lại khi mở modal hoặc đổi profile.
  useEffect(() => {
    if (!open) return;
    exportMut.mutate(profile);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ chạy khi mở/đổi profile
  }, [open, profile]);

  const pickProfile = (key: WebChatProfile) => {
    setProfile(key);
    setPreview(null);
    setImportError("");
  };

  const exportData = exportMut.data;
  const skippedInfo =
    exportData && exportData.skipped.length > 0
      ? `${exportData.skipped.length} chương bị bỏ qua (thiếu raw/dịch).`
      : null;
  const countInfo =
    exportData && current.source === "glossary"
      ? `Detected ${exportData.count ?? 0} mục glossary trong ${exportData.total} chương.`
      : `Xuất ${exportData?.total ?? 0} chương.`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Web chat — xuất / nhập dữ liệu AI"
      wide
      footer={
        tab === "export" ? (
          <>
            <Button
              variant="neutral"
              loading={exportMut.isPending}
              disabled={!exportData}
              onClick={() => navigator.clipboard.writeText(exportData!.text).then(() => toast("Đã sao chép."))}
            >
              Sao chép
            </Button>
            <Button onClick={onClose}>Đóng</Button>
          </>
        ) : (
          <>
            {profile === "glossary" ? (
              <Button
                variant="primary"
                loading={importMut.isPending}
                disabled={!importText.trim()}
                onClick={() => importMut.mutate("confirm")}
              >
                Nhập vào glossary
              </Button>
            ) : preview ? (
              <Button
                variant="primary"
                loading={importMut.isPending}
                onClick={() => importMut.mutate("confirm")}
              >
                Xác nhận ghi
              </Button>
            ) : (
              <Button
                variant="primary"
                loading={importMut.isPending}
                disabled={!importText.trim()}
                onClick={() => importMut.mutate("preview")}
              >
                Xem trước
              </Button>
            )}
            <Button onClick={onClose}>Đóng</Button>
          </>
        )
      }
    >
      <div className="mb-2 flex items-center gap-1.5">
        <Button size="sm" variant={tab === "export" ? "primary" : "neutral"} onClick={() => setTab("export")}>
          Xuất
        </Button>
        <Button size="sm" variant={tab === "import" ? "primary" : "neutral"} onClick={() => setTab("import")}>
          Nhập
        </Button>
        <Select value={profile} onChange={(e) => pickProfile(e.target.value as WebChatProfile)} className="ml-3">
          {WEB_CHAT_PROFILES.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
        </Select>
      </div>

      {tab === "export" ? (
        <>
          <p className="mb-2 text-xs opacity-60">{current.hint}</p>
          {exportMut.isPending && !exportData ? (
            <Loading label="Đang xuất" />
          ) : (
            <>
              <p className="mb-2 text-xs opacity-60">
                {countInfo}
                {skippedInfo ? ` ${skippedInfo}` : ""}
              </p>
              <Textarea readOnly value={exportData?.text ?? ""} rows={16} className="w-full font-mono text-xs" />
            </>
          )}
        </>
      ) : (
        <>
          <p className="mb-2 text-xs opacity-60">
            {profile === "glossary"
              ? "Dán khối ## GLOSSARY AI trả về để merge vào glossary."
              : "Dán kết quả AI (kèm marker ## idx:N) để ghi đè bản dịch."}
          </p>
          <Textarea
            value={importText}
            onChange={(e) => {
              setImportText(e.target.value);
              setPreview(null);
              setImportError("");
            }}
            rows={16}
            className="w-full font-mono text-xs"
            placeholder={profile === "glossary" ? "## GLOSSARY\n李逸 = Lý Dịch" : "## idx:5: Chương 5: ..."}
          />
          {preview ? (
            <div className="mt-2 rounded-box border border-base-300 p-2.5 text-xs">
              <p className="font-medium">
                {preview.chapters.filter((c) => c.changed).length} chương thay đổi,{" "}
                {preview.chapters.length - preview.chapters.filter((c) => c.changed).length} không đổi.
              </p>
              {preview.unknown.length > 0 && (
                <p className="opacity-70">Không tìm thấy trong manifest: {preview.unknown.join(", ")}</p>
              )}
              {preview.extra.length > 0 && (
                <p className="opacity-70">Ngoài danh sách chọn: {preview.extra.join(", ")}</p>
              )}
              {Object.keys(preview.glossary_new).length > 0 && (
                <p className="opacity-70">Glossary mới: {Object.keys(preview.glossary_new).join(", ")}</p>
              )}
            </div>
          ) : null}
          {importError ? <p className="mt-2 text-xs text-error">{importError}</p> : null}
        </>
      )}
    </Modal>
  );
}

/**
 * Hộp thoại "Dọn chữ Hán" — rà bản dịch, dịch nốt vùng chữ Hán còn sót.
 *
 * Hai engine KHÔNG thay thế được cho nhau nên phải chọn tường minh, không có
 * mặc định ngầm trong UI: Local MT chạy offline, miễn phí, hợp với việc quét
 * cả nghìn chương; AI biên tập tốn tiền theo token nhưng xử lý được các đoạn
 * mà MT cục bộ trả về lổn nhổn. Bỏ trống = theo cấu hình truyện
 * (Cài đặt → Dịch → Dọn chữ Hán).
 */
function CleanupHanDialog({
  open,
  onClose,
  slug,
  indexes,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  slug: string;
  indexes: number[];
  onDone: () => void;
}) {
  const toast = useToast();
  const [engine, setEngine] = useState("");
  const [force, setForce] = useState(false);

  const run = useMutation({
    mutationFn: () =>
      api.post<{ started: boolean; total: number }>(`/api/ebooks/${slug}/batch/cleanup-han`, {
        form: {
          indexes: indexes.join(","),
          ...(engine ? { engine } : {}),
          force: String(force),
        },
      }),
    onSuccess: (res) => {
      toast(`Đã xếp job dọn chữ Hán cho ${num(res.total)} chương vào hàng đợi.`);
      onDone();
      onClose();
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  return (
    <ConfirmDialog
      open={open}
      onCancel={onClose}
      onConfirm={() => run.mutate()}
      title="Dọn chữ Hán"
      confirmLabel="Xếp vào hàng đợi"
      pending={run.isPending}
      body={
        <div className="space-y-3">
          <p>
            Rà bản dịch của <strong data-numeric>{num(indexes.length)}</strong> chương đã chọn và
            dịch nốt những đoạn còn nguyên chữ Hán. Chương chưa có bản dịch được bỏ qua.
          </p>
          <label className="flex items-center gap-2 text-[13px]">
            <span className="w-16 shrink-0 opacity-70">Engine</span>
            <Select value={engine} onChange={(e) => setEngine(e.target.value)} className="w-52">
              <option value="">Theo cấu hình truyện</option>
              <option value="local_mt">Local MT — offline, miễn phí</option>
              <option value="openai">AI biên tập — tốn token</option>
            </Select>
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-[13px]">
            <Checkbox checked={force} onChange={(event) => setForce(event.target.checked)} />
            Quét lại cả chương đã dọn trước đó
          </label>
          <p className="text-[11px] opacity-60">
            Bản dịch cũ được giữ trong snapshot nên có thể so sánh và khôi phục.
          </p>
        </div>
      }
    />
  );
}

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
  const [includeTranslatedTitle, setIncludeTranslatedTitle] = useState(true);
  const [includeZhTitle, setIncludeZhTitle] = useState(false);
  const [translateAction, setTranslateAction] = useState<"translate" | "local-mt" | null>(null);
  const [translateForce, setTranslateForce] = useState(false);
  const [aiEditOpen, setAiEditOpen] = useState(false);
  const [webChatOpen, setWebChatOpen] = useState(false);
  const [cleanupHanOpen, setCleanupHanOpen] = useState(false);
  const [branchAiOpen, setBranchAiOpen] = useState(false);

  const setBranchAi = useMutation({
    mutationFn: () =>
      api.post<{ updated: number; skipped: number; branch: string }>(
        `/api/ebooks/${slug}/batch/set-branch`,
        { form: { indexes: selected.join(","), branch: "ai" } },
      ),
    onSuccess: (res) => {
      setBranchAiOpen(false);
      onDone();
      const skipped =
        res.skipped > 0
          ? `, bỏ qua ${num(res.skipped)} chương chưa có bản dịch AI`
          : "";
      toast(`Đã chuyển ${num(res.updated)} chương sang bản dịch AI${skipped}.`);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

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
          include_zh: String(includeZhTitle),
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

  /** Sắp xếp chương chạy trực tiếp (không qua job queue): backend ghi manifest
      ngay trong request và trả về các phép đảo vị trí cũ → mới để liệt kê. */
  const reorderRun = useMutation({
    mutationFn: (form: Record<string, string>) =>
      api.post<ReorderResult>(`/api/ebooks/${slug}/jobs/reorder`, { form }),
    onSuccess: (res) => {
      setReorderMode(null);
      setManualIndexes("");
      onDone();
      const shown = res.changes.slice(0, 3).map((c) => `#${c.index}: ${c.from}→${c.to}`);
      const hidden = res.moved - shown.length;
      const detail = shown.length > 0 ? ` (${shown.join(", ")}${hidden > 0 ? ` +${hidden}` : ""})` : "";
      toast(
        res.moved > 0
          ? `Đã sắp xếp ${res.total} chương, ${res.moved} đổi vị trí${detail}.`
          : `Thứ tự ${res.total} chương đã đúng, không có gì đổi.`,
      );
    },
    // Giữ hộp thoại mở để sửa lại input khi lỗi.
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
    reorderRun.mutate(
      reorderMode === "manual" ? { order: indexes.join(",") } : { order: "auto" },
    );
  };

  const applyTocAction: BatchAction = {
    ...NORMALIZE_TOC_ACTION,
    form: {
      apply: "true",
      include_translated: String(includeTranslatedTitle),
      include_zh: String(includeZhTitle),
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
            <span className="text-[10px] tracking-[0.1em] uppercase opacity-40">Crawl</span>
            <Button
              size="sm"
              title="Tải nội dung gốc cho các chương đã chọn (bỏ qua chương đã có raw)"
              onClick={() => trigger(CRAWL_ACTION)}
            >
              Crawl
            </Button>
            <Button
              size="sm"
              title="Tải LẠI bản gốc kể cả chương đã có raw — raw cũ bị ghi đè"
              onClick={() => trigger(CRAWL_FORCE_ACTION)}
            >
              ↻ Force
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
              title="AI biên tập GHI TRỰC TIẾP vào nhánh Local MT (bản gốc MT giữ trong snapshot) — xem xác nhận trước khi xếp job"
              onClick={() => setAiEditOpen(true)}
            >
              Biên tập AI
            </Button>
            <Button
              size="sm"
              title="Dịch nốt những đoạn còn nguyên chữ Hán trong bản dịch đã có"
              onClick={() => setCleanupHanOpen(true)}
            >
              Dọn chữ Hán
            </Button>
          </div>

          <div className="h-8 w-px bg-base-300" aria-hidden="true" />

          <div className="flex items-center gap-1.5">
            <span className="text-[10px] tracking-[0.1em] uppercase opacity-40">Nhánh</span>
            <Button
              size="sm"
              variant="primary"
              title="Chuyển các chương đã chọn sang bản dịch AI — tiêu đề sẽ hiển thị theo Tiêu đề bản Dịch AI (tránh bấm Chuyển thủ công từng chương)"
              onClick={() => setBranchAiOpen(true)}
            >
              Dùng bản dịch AI
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
              Bản dịch
            </label>
            <label
              className="flex cursor-pointer items-center gap-1.5 text-[11px] opacity-70"
              title="Tiêu đề gốc tham gia nhận diện chương mới; chỉ bật khi chấp nhận lần cập nhật TOC sau có thể thấy tiêu đề nguồn khác."
            >
              <Checkbox
                checked={includeZhTitle}
                onChange={(event) => setIncludeZhTitle(event.target.checked)}
              />
              Gốc (zh)
            </label>
          </div>

          <div className="h-8 w-px bg-base-300" aria-hidden="true" />

          <div className="flex items-center gap-1.5">
            <span className="text-[10px] tracking-[0.1em] uppercase opacity-40">Web chat</span>
            <Button size="sm" icon={<IconChat size={13} />} onClick={() => setWebChatOpen(true)}>
              Xuất / Nhập
            </Button>
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
        force={translateForce}
        indexes={selected}
        title={`Dịch bằng ${branchLabel}`}
        body={
          <>
            Dịch {selected.length} chương đã chọn vào nhánh{" "}
            <strong>{branchLabel}</strong>. Chương nào đã có bản dịch trong nhánh đó sẽ được{" "}
            <strong>bỏ qua</strong>, không ghi đè.
          </>
        }
        bodyExtra={
          <label className="flex cursor-pointer items-center gap-2 text-[13px]">
            <Checkbox
              checked={translateForce}
              onChange={(event) => setTranslateForce(event.target.checked)}
            />
            Dịch lại cả chương đã có bản dịch ở nhánh này (force — bản dịch cũ được thay)
          </label>
        }
        confirmLabel="Xếp vào hàng đợi"
        onDone={onDone}
      />

      <BulkPreviewDialog
        open={aiEditOpen}
        onClose={() => setAiEditOpen(false)}
        slug={slug}
        action="ai-edit"
        indexes={selected}
        title={`Biên tập AI ${selected.length} chương`}
        body={
          <>
            AI đọc bản dịch <strong>Local MT</strong> của các chương đã chọn và{" "}
            <strong>ghi kết quả TRỰC TIẾP vào nhánh Local MT</strong> (bản gốc dịch máy được giữ
            trong snapshot để so sánh/khôi phục). Chương nào có Local MT sẽ bị{" "}
            <strong>ghi đè</strong> — xem danh sách phía dưới rồi xác nhận.
          </>
        }
        confirmLabel="Xếp vào hàng đợi"
        onDone={onDone}
      />

      <WebChatDialog
        open={webChatOpen}
        onClose={() => setWebChatOpen(false)}
        slug={slug}
        indexes={selected}
        onDone={onDone}
      />

      <CleanupHanDialog
        open={cleanupHanOpen}
        onClose={() => setCleanupHanOpen(false)}
        slug={slug}
        indexes={selected}
        onDone={onDone}
      />

      <ConfirmDialog
        open={branchAiOpen}
        onCancel={() => setBranchAiOpen(false)}
        onConfirm={() => setBranchAi.mutate()}
        title="Dùng bản dịch AI"
        confirmLabel="Chuyển sang AI"
        pending={setBranchAi.isPending}
        body={
          <p>
            Chuyển <strong data-numeric>{num(selected.length)}</strong> chương đã chọn sang nhánh
            bản dịch AI. Tiêu đề hiển thị (TOC/Reader/EPUB) sẽ tự cập nhật theo{" "}
            <strong>Tiêu đề bản Dịch AI</strong>. Chương chưa có bản dịch AI sẽ bị bỏ qua. Thao tác
            này không ghi đè nội dung bản dịch.
          </p>
        }
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
        pending={reorderRun.isPending}
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
                        {Object.entries(change.branches ?? {}).map(([branch, fields]) => (
                          <div key={branch} className="rounded-box border border-base-300 bg-base-100 px-2 py-1.5">
                            <p className="text-[10px] font-semibold tracking-[0.08em] uppercase opacity-45">
                              {branch === "local_mt" ? "Local MT" : "AI"}
                            </p>
                            {fields.title ? (
                              <TocTitleDiff label="Đã dịch" before={fields.title[0]} after={fields.title[1]} />
                            ) : null}
                            {fields.title_zh ? (
                              <TocTitleDiff label="Gốc" before={fields.title_zh[0]} after={fields.title_zh[1]} />
                            ) : null}
                          </div>
                        ))}
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
                Các phần (上)/(中)/(下), (Thượng)/(Hạ) và số thứ tự (1), (2) được giữ lại. Chỉ ghi dữ
                liệu sau khi xác nhận.
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

/* ── Phân trang ──────────────────────────────────────────────────────── */

/**
 * Thanh phân trang + chọn số dòng mỗi trang.
 *
 * Đặt được ở CẢ HAI đầu bảng: trước đây chỉ có ở chân, nên với 100 dòng thì
 * muốn sang trang là phải cuộn hết bảng — trong khi mọi thứ khác (bộ lọc, nút
 * chọn tất cả) đều nằm ở đầu. `variant` chỉ đổi đường viền để hai thanh không
 * tạo ra hai vạch kẻ chồng nhau.
 */
function TablePager({
  offset,
  pageSize,
  matched,
  variant,
  onOffset,
  onPageSize,
}: {
  offset: number;
  pageSize: number;
  matched: number;
  variant: "top" | "bottom";
  /** Nhận cả dạng hàm cập nhật để "Trước"/"Sau" không đọc `offset` cũ khi
      bấm liên tiếp trong cùng một nhịp render. */
  onOffset: (next: number | ((prev: number) => number)) => void;
  onPageSize?: (next: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(matched / pageSize));
  const current = Math.floor(offset / pageSize) + 1;
  const first = matched === 0 ? 0 : offset + 1;
  const last = Math.min(offset + pageSize, matched);

  return (
    <div
      className={clsx(
        "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-3 py-2",
        variant === "top" ? "border-b border-base-300" : "border-t border-base-300",
      )}
    >
      <div className="flex items-center gap-3">
        {onPageSize ? (
          <label className="flex items-center gap-1.5 text-[11px] opacity-70">
            Hiện
            <Select
              value={String(pageSize)}
              onChange={(event) => onPageSize(Number(event.target.value))}
              className="w-20"
              aria-label="Số chương mỗi trang"
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </Select>
            dòng
          </label>
        ) : null}
        <span data-numeric className="text-[11px] opacity-60">
          {num(first)}–{num(last)} / {num(matched)}
        </span>
      </div>

      <div className="flex items-center gap-1.5">
        <span data-numeric className="mr-1 text-[11px] opacity-60">
          Trang {num(current)}/{num(pageCount)}
        </span>
        <Button size="sm" disabled={offset === 0} onClick={() => onOffset(0)} title="Trang đầu">
          «
        </Button>
        <Button
          size="sm"
          disabled={offset === 0}
          onClick={() => onOffset((prev) => Math.max(0, prev - pageSize))}
        >
          Trước
        </Button>
        <Button
          size="sm"
          disabled={offset + pageSize >= matched}
          onClick={() =>
            onOffset((prev) => Math.min(prev + pageSize, Math.max(0, (pageCount - 1) * pageSize)))
          }
        >
          Sau
        </Button>
        <Button
          size="sm"
          disabled={offset + pageSize >= matched}
          onClick={() => onOffset((pageCount - 1) * pageSize)}
          title="Trang cuối"
        >
          »
        </Button>
      </div>
    </div>
  );
}

/* ── Bảng chương ─────────────────────────────────────────────────────── */

/**
 * Badge một nhánh dịch (Local MT / AI).
 *
 * Trước đây cột trạng thái viết thành câu — "Local MT có · AI —" — vừa dài vừa
 * bắt đọc chữ mới biết được/mất. Ở đây trạng thái nằm hết trong hình thức:
 * nhánh có dữ liệu thì badge đặc, chưa có thì viền đứt và mờ; nhánh đang
 * active có vòng ngoài vì đó mới là bản đi vào EPUB/Reader.
 */
function BranchBadge({
  label,
  has,
  active,
}: {
  label: string;
  has: boolean;
  active: boolean;
}) {
  const state = has ? "đã có bản dịch" : "chưa có bản dịch";
  return (
    <span
      title={`${label}: ${state}${active ? " · đang là nhánh xuất bản" : ""}`}
      className={clsx(
        "inline-flex items-center rounded-selector px-1.5 py-px text-[10px] font-medium tracking-wide",
        has
          ? "bg-success/15 text-success"
          : "border border-dashed border-base-content/25 text-base-content/40",
        active && "ring-1 ring-primary/60",
      )}
    >
      {label}
    </span>
  );
}

/** Cột trạng thái chỉ giữ tiến độ chính và các cảnh báo cần người xử lý. */
function ChapterStatusCell({ row }: { row: ChapterRow }) {
  const warnings = rowWarnings(row);
  return (
    <div className="flex items-center gap-1.5 whitespace-nowrap text-[11px]">
      <Dot tone={rowTone(row)} />
      <span className={clsx(row.skipped ? "opacity-45" : "opacity-80")}>{rowLabel(row)}</span>
      {row.bientap ? (
        <span
          title={row.bientap_tooltip}
          className="inline-flex items-center rounded-selector bg-info/15 px-1.5 py-px text-[10px] font-medium text-info"
        >
          {/* Bỏ emoji dẫn đầu ("📝", "✏️") — badge đã có màu riêng, thêm
              emoji nữa thì cột trạng thái rối. `\p{Emoji_Presentation}`
              KHÔNG khớp "✏️" (U+270F là ký tự text, chỉ thành emoji nhờ
              VS16) nên phải cắt theo "mọi ký tự không phải chữ/số". */}
          {row.bientap.replace(/^[^\p{L}\p{N}]+/u, "")}
        </span>
      ) : null}
      {warnings.map((warning) => (
        <span
          key={warning.key}
          title={warning.hint}
          className="inline-flex items-center rounded-selector bg-error/15 px-1.5 py-px text-[10px] font-medium text-error"
        >
          {warning.label}
        </span>
      ))}
    </div>
  );
}

function ChapterTableRow({
  slug,
  row,
  checked,
  showZhTitle,
  onSelect,
}: {
  slug: string;
  row: ChapterRow;
  checked: boolean;
  showZhTitle: boolean;
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
      <td data-numeric className="w-10 px-2 py-1 text-xs opacity-60">
        {row.index}
      </td>
      <td className="px-2 py-1">
        <div className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1">
            <Link
              to={`/ebooks/${slug}/chapters/${row.index}`}
              className={clsx("block truncate text-[13px] hover:text-primary", row.skipped && "line-through opacity-50")}
            >
              {row.visible_title}
            </Link>
            {showZhTitle && row.title_zh ? (
              <span
                dir="rtl"
                className="block truncate text-[11px] text-base-content/55"
                title={row.title_zh}
              >
                {row.title_zh}
              </span>
            ) : null}
          </div>
          {/* Chương trùng và tiêu đề sai mẫu đã có badge ở cột trạng thái; ở đây
              chỉ đánh dấu tiêu đề lỗi ngay tại chỗ đọc để khỏi phải liếc ngang. */}
          {!row.title_format_ok ? (
            <span
              title='Tiêu đề sai mẫu "Chương N[: tên chương]" hoặc còn chữ Hán.'
              className="shrink-0 text-[11px] text-error"
            >
              ⚠
            </span>
          ) : null}
        </div>
      </td>
      <td className="w-48 px-2 py-1">
        <ChapterStatusCell row={row} />
      </td>
      <td className="w-12 px-2 py-1 text-center">
        <BranchBadge
          label="MT"
          has={row.has_local_mt_translation}
          active={row.active_branch === "local_mt"}
        />
      </td>
      <td className="w-12 px-2 py-1 text-center">
        <BranchBadge label="AI" has={row.has_ai_translation} active={row.active_branch === "ai"} />
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
  const toast = useToast();
  const [, selectBook] = useCurrentBook();
  const [filters, setFilters] = useState<ChapterFilters>(() => loadChapterFilters(slug));
  const [offset, setOffset] = useState(() => loadPage(slug));
  const [pageSize, setPageSize] = useState(() => loadPageSize(slug));
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [lastToggled, setLastToggled] = useState<number | null>(null);
  const [readerPreview, setReaderPreview] = useState<ReaderPublishPreview | null>(null);

  const previewReader = useMutation({
    mutationFn: () => api.get<ReaderPublishPreview>(`/api/ebooks/${slug}/publish/preview`),
    onSuccess: (preview) => {
      if (!preview.new && !preview.edited) {
        toast(`Không có gì để đẩy. ${preview.unchanged} chương đã đồng bộ, ${preview.skipped} chương bị bỏ qua.`);
        return;
      }
      setReaderPreview(preview);
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const publishReader = useMutation({
    mutationFn: () => api.post<{ started: boolean }>(`/api/ebooks/${slug}/publish/push`),
    onSuccess: () => {
      setReaderPreview(null);
      client.invalidateQueries({ queryKey: queueKey });
      toast("Đã xếp job đẩy lên Reader vào hàng đợi.");
      navigate("/queue");
    },
    onError: (err) => toast(err instanceof Error ? err.message : String(err), "error"),
  });

  const { data: book, isPending, error } = useEbook(slug);
  // Ô tìm kiếm chỉ đẩy lên API sau khi ngừng gõ — giữ nguyên tham chiếu
  // `filters` khi đã bắt kịp để không tạo request thừa do queryKey đổi.
  const debouncedSearch = useDebouncedValue(filters.search);
  const queryFilters = useMemo(
    () => (debouncedSearch === filters.search ? filters : { ...filters, search: debouncedSearch }),
    [filters, debouncedSearch],
  );
  const { data: page, isFetching, isPending: chaptersPending } = useChapters(
    slug,
    queryFilters,
    offset,
    pageSize,
  );

  /** Khoảng trống index giữa hai dòng đang hiển thị, kèm SUY LUẬN số chương
      thật từ tiêu đề lân cận. Nếu hai chương hai bên có số chương liên tiếp
      đúng bằng bề rộng khoảng trống (vd #122 "Chương 122" → #124 "Chương 123")
      thì đó là index do NGUỒN bỏ trống — không phải thiếu nội dung cần điền. */
  const indexGaps = useMemo(() => {
    if (!page?.rows.length) return [];
    const sorted = [...page.rows].sort((a, b) => a.index - b.index);
    return sorted.flatMap((row, position) => {
      const next = sorted[position + 1];
      if (!next || next.index === row.index + 1) return [];
      const missingCount = next.index - row.index - 1;
      const beforeOrdinal = chapterOrdinal(row.visible_title, row.title_zh);
      const afterOrdinal = chapterOrdinal(next.visible_title, next.title_zh);
      const benign =
        beforeOrdinal !== null &&
        afterOrdinal !== null &&
        afterOrdinal - beforeOrdinal === missingCount;
      return [{
        from: row.index + 1,
        to: next.index - 1,
        before: row,
        after: next,
        beforeOrdinal,
        afterOrdinal,
        benign,
      }];
    });
  }, [page?.rows]);

  // Mở thẳng trang truyện cũng là "đang làm truyện này" — thanh điều hướng
  // phải theo, nếu không người dùng thấy hai truyện khác nhau trên cùng màn.
  useEffect(() => {
    if (slug) selectBook(slug);
  }, [slug, selectBook]);

  // Đổi bộ lọc thì tập kết quả khác hẳn — về trang đầu và bỏ chọn.
  //
  // So sánh THAM CHIẾU của `filters` chứ không đếm số lần chạy: effect có deps
  // vẫn chạy sau lần mount đầu, và StrictMode ở dev còn chạy lại lần nữa — cả
  // hai lần đó đều xóa mất trang vừa khôi phục từ localStorage. `filters` chỉ
  // đổi identity khi `setFilters` được gọi, nên đây đúng là "người dùng vừa
  // đổi bộ lọc".
  const lastFilters = useRef(filters);
  useEffect(() => {
    if (lastFilters.current === filters) return;
    lastFilters.current = filters;
    setOffset(0);
    setSelected(new Set());
    setLastToggled(null);
  }, [filters]);

  // Bộ lọc đã lưu có thể khớp ít kết quả hơn lần trước (chương bị xóa, đổi
  // bộ lọc ở tab khác) — offset khôi phục khi đó trỏ ra ngoài danh sách và
  // bảng hiện rỗng dù vẫn có kết quả. Kéo về trang cuối còn dữ liệu.
  useEffect(() => {
    if (page && offset > 0 && offset >= page.matched) {
      setOffset(Math.max(0, Math.floor((page.matched - 1) / pageSize) * pageSize));
    }
  }, [page, offset, pageSize]);

  // Giữ bộ lọc + sắp xếp + trang + cỡ trang qua các lần vào lại trang truyện này.
  useEffect(() => {
    try {
      window.localStorage.setItem(CHAPTER_FILTERS_KEY(slug), JSON.stringify(filters));
      window.localStorage.setItem(PAGE_KEY(slug), String(offset));
      window.localStorage.setItem(PAGE_SIZE_KEY(slug), String(pageSize));
    } catch {
      // Quota đầy hoặc ẩn danh — bỏ qua, chỉ mất lần lưu này.
    }
  }, [slug, filters, offset, pageSize]);

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

  // Đổi trang xóa mốc Shift: dải chọn chỉ có nghĩa trong các dòng đang thấy.
  const goToOffset = (next: number | ((prev: number) => number)) => {
    setOffset((prev) => Math.max(0, typeof next === "function" ? next(prev) : next));
    setLastToggled(null);
  };

  /** Đổi cỡ trang giữ nguyên dòng đầu đang xem, làm tròn về đầu trang mới. */
  const changePageSize = (next: number) => {
    setPageSize(next);
    setOffset(Math.floor(offset / next) * next);
    setLastToggled(null);
  };

  const refresh = () => {
    client.invalidateQueries({ queryKey: ebookKey(slug) });
    client.invalidateQueries({ queryKey: ["chapters", slug] });
    client.invalidateQueries({ queryKey: queueKey });
    setSelected(new Set());
    setLastToggled(null);
  };

  if (isPending) {
    return (
      <Page title="Đang tải" loading loadingLabel="Đang đọc dữ liệu truyện">
        {null}
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
          <PipelineBar slug={slug} epubExists={book.epub_exists} />
          <Button
            loading={previewReader.isPending}
            disabled={!book.reader_configured || publishReader.isPending}
            title={book.reader_configured ? "Xem trước và đẩy bản dịch lên Reader" : "Chưa cấu hình Reader"}
            onClick={() => previewReader.mutate()}
          >
            Đẩy Reader
          </Button>
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

      <ConfirmDialog
        open={readerPreview !== null}
        onCancel={() => setReaderPreview(null)}
        onConfirm={() => publishReader.mutate()}
        title="Đẩy lên Reader?"
        confirmLabel="Đẩy lên Reader"
        pending={publishReader.isPending}
        body={readerPreview ? (
          <div className="space-y-1">
            <p>Thêm mới: <strong data-numeric>{num(readerPreview.new)}</strong> chương</p>
            <p>Cập nhật: <strong data-numeric>{num(readerPreview.edited)}</strong> chương</p>
            <p>Không đổi: <strong data-numeric>{num(readerPreview.unchanged)}</strong> chương</p>
            <p>Bỏ qua: <strong data-numeric>{num(readerPreview.skipped)}</strong> chương chưa dịch xong hoặc bị skip</p>
            <p className="pt-2 opacity-60">Không có chương nào bị xóa trên Reader.</p>
          </div>
        ) : null}
      />

      {indexGaps.length > 0 ? (
        <details className="group mb-3 rounded-box border border-error/40 bg-error/10 text-[13px]">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 marker:content-none">
            <Dot tone="vermilion" />
            <span className="font-medium">
              Trống {num(indexGaps.reduce((total, gap) => total + gap.to - gap.from + 1, 0))} index
              trong {num(indexGaps.length)} khoảng trên trang này
              <span className="ml-1 font-normal opacity-70">
                ({num(indexGaps.filter((gap) => !gap.benign).length)} nghi thiếu nội dung)
              </span>
            </span>
            <span className="ml-auto text-[11px] opacity-60 group-open:hidden">Xem chi tiết</span>
            <span className="ml-auto hidden text-[11px] opacity-60 group-open:inline">Thu gọn</span>
          </summary>
          <div className="border-t border-error/20 px-3 py-2">
            <p className="mb-2 text-[11px] opacity-70">
              Số chương thật được suy từ tiêu đề hai chương lân cận. Hai bên liền số → nguồn bỏ
              trống index, không cần crawl thêm; hụt số → có thể đang thiếu chương.
            </p>
            <ul className="space-y-1.5">
              {indexGaps.map((gap) => (
                <li
                  key={`${gap.from}-${gap.to}`}
                  className="grid gap-1 rounded-box bg-base-100/60 px-2.5 py-2 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-3"
                >
                  <span
                    data-numeric
                    className={clsx("font-medium", gap.benign ? "text-warning" : "text-error")}
                    title={gap.benign ? "Hai bên liền số chương — nguồn không có các index này." : "Số chương hai bên hụt — kiểm tra xem có chương bị bỏ sót không."}
                  >
                    {gap.benign ? "Nhảy" : "Thiếu"} #{gap.from}{gap.to > gap.from ? `–${gap.to}` : ""}
                  </span>
                  <span className="min-w-0 text-[11px] opacity-70">
                    Sau <Link className="font-medium hover:text-primary" to={`/ebooks/${slug}/chapters/${gap.before.index}`}>#{gap.before.index} {gap.before.visible_title}</Link>
                    {" · trước "}
                    <Link className="font-medium hover:text-primary" to={`/ebooks/${slug}/chapters/${gap.after.index}`}>#{gap.after.index} {gap.after.visible_title}</Link>
                    {gap.beforeOrdinal !== null && gap.afterOrdinal !== null ? (
                      <>
                        {" — "}
                        <span data-numeric>số chương {num(gap.beforeOrdinal)} → {num(gap.afterOrdinal)}</span>
                        {gap.benign ? " (liền nhau)" : " (hụt)"}
                      </>
                    ) : (
                      " — không suy được số chương từ tiêu đề"
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </details>
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
          <ChapterStrip
            states={states}
            height={30}
            onSelect={(index) => navigate(`/ebooks/${slug}/chapters/${index + 1}`)}
          />
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

        {page ? (
          <TablePager
            offset={offset}
            pageSize={pageSize}
            matched={page.matched}
            variant="top"
            onOffset={goToOffset}
            onPageSize={changePageSize}
          />
        ) : null}

        {chaptersPending ? (
          <SkeletonTable rows={Math.min(pageSize, 10)} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={book.has_manifest ? "Không có chương nào khớp" : "Chưa có mục lục"}
            hint={
              book.has_manifest
                ? "Nới bộ lọc hoặc xóa từ khóa tìm kiếm."
                : "Chạy bước Lấy mục lục để nạp danh sách chương từ nguồn."
            }
          />
        ) : (
          <div className={clsx("overflow-x-auto", isFetching && "is-refetching")}>
            <table className="w-full min-w-[58rem] table-fixed border-collapse text-left">
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
                  {["#", "Tiêu đề", "Trạng thái", "MT", "AI", "Bản gốc", "Bản dịch", ""].map((h, i) => (
                    <th
                      key={h || i}
                      className={clsx(
                        "px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] uppercase opacity-40",
                        h === "#" && "w-10",
                        h === "Tiêu đề" && "w-[22rem]",
                        (h === "MT" || h === "AI") && "text-center",
                        (h === "Bản gốc" || h === "Bản dịch") && "text-right",
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
                    showZhTitle={filters.show_zh_title}
                    onSelect={selectRow}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {page && page.matched > pageSize ? (
          <TablePager
            offset={offset}
            pageSize={pageSize}
            matched={page.matched}
            variant="bottom"
            onOffset={goToOffset}
          />
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
