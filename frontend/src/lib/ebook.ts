import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface EbookDetail {
  slug: string;
  title: string;
  author: string;
  language: string;
  series: string;
  toc_url: string;
  crawl_mode: string;
  translate_type: string;
  translate_model: string;
  has_manifest: boolean;
  total: number;
  raw_count: number;
  translated_count: number;
  strip: string;
  counts: Record<string, number>;
  crawl_problems: number[];
  epub_exists: boolean;
  epub_path: string;
  epub_size: number;
  cost_summary: CostSummary | null;
  reader_configured: boolean;
  active_jobs: { id: string; label: string; step: string }[];
}

export interface CostSummary {
  chapter_count: number;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_model: Record<string, { cost_usd: number; chapters: number }>;
}

export interface ChapterRow {
  index: number;
  title: string;
  visible_title: string;
  /** Tiêu đề nguồn tiếng Trung trong manifest — cho "Hiển thị zh_title"
      và suy luận số chương thật khi tiêu đề dịch thiếu số. */
  title_zh: string;
  url: string;
  has_raw: boolean;
  /** Bản dịch hoàn tất ở nhánh đang active (thứ Reader/EPUB sử dụng). */
  has_translated: boolean;
  active_branch: "ai" | "local_mt";
  has_ai_translation: boolean;
  has_local_mt_translation: boolean;
  missing_fields: string[];
  duplicate_of: number | null;
  last_action_status: string;
  word_count: number;
  zh_char_count: number;
  bientap: string;
  bientap_tooltip: string;
  skipped: boolean;
  /** Tiêu đề nhánh active đúng mẫu "Chương N[: tên]" và không còn chữ Hán. */
  title_format_ok: boolean;
}

export interface ChapterPage {
  rows: ChapterRow[];
  total: number;
  matched: number;
  /** Mọi index khớp bộ lọc — để "chọn tất cả" không phải tải hết từng dòng. */
  indexes: number[];
}

export interface ChapterFilters {
  search: string;
  sort: string;
  direction: string;
  filter_raw: string;
  /** Nhánh ĐANG ACTIVE có bản dịch — thứ đi vào EPUB/Reader. */
  filter_translated: string;
  /** Nhánh Local MT có bản dịch, độc lập với nhánh nào đang active. */
  filter_local_mt: string;
  /** Nhánh AI có bản dịch, độc lập với nhánh nào đang active. */
  filter_ai: string;
  filter_missing: string;
  /** "yes" = chỉ chương sai mẫu "Chương N[: tên]" hoặc còn chữ Hán. */
  filter_title_error: string;
  filter_skipped: string;
  /** Hiện tiêu đề tiếng Trung ngay dưới tiêu đề đã dịch trong bảng chương. */
  show_zh_title: boolean;
}

export const DEFAULT_FILTERS: ChapterFilters = {
  search: "",
  sort: "source",
  direction: "asc",
  filter_raw: "any",
  filter_translated: "any",
  filter_local_mt: "any",
  filter_ai: "any",
  filter_missing: "any",
  filter_title_error: "any",
  filter_skipped: "any",
  show_zh_title: false,
};

/** Khóa localStorage lưu bộ lọc bảng chương trên trang Sách — dùng chung để
    trang Chương (drawer danh sách) có thể tái dùng đúng bộ lọc đang áp dụng. */
export const CHAPTER_FILTERS_KEY = (slug: string) => `ebooks.${slug}.chapterFilters`;

/** Nạp bộ lọc đã lưu cho truyện, hợp nhất với mặc định để khỏi vỡ schema.
    Chỉ nhận đúng kiểu khai báo — string cho bộ lọc/sắp xếp, boolean cho cờ
    hiển thị (show_zh_title); kiểu khác bị bỏ qua. */
export function loadChapterFilters(slug: string): ChapterFilters {
  try {
    const raw = window.localStorage.getItem(CHAPTER_FILTERS_KEY(slug));
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const merged = { ...DEFAULT_FILTERS };
      const target = merged as unknown as Record<string, unknown>;
      for (const key of Object.keys(merged) as (keyof ChapterFilters)[]) {
        const value = parsed[key];
        if (typeof value === "string" && typeof DEFAULT_FILTERS[key] === "string") {
          target[key] = value;
        } else if (typeof value === "boolean" && typeof DEFAULT_FILTERS[key] === "boolean") {
          target[key] = value;
        }
      }
      return merged;
    }
  } catch {
    // Mất localStorage là không đáng kể — dùng mặc định.
  }
  return DEFAULT_FILTERS;
}

export interface Paragraph {
  raw: string;
  mt: string;
  edited: string;
}

/** Hàng của khung đối chiếu 4 cột (SPA): bản gốc | Local MT | Dịch AI | AI edit.
    `mt`/`edited` là field legacy (baseline dịch máy và bản hiện tại của nhánh
    `local_mt`) giữ cho client cũ không vỡ khi parse. */
export interface Paragraph4 {
  raw: string;
  local_mt: string;
  ai: string;
  ai_edit: string;
  mt: string;
  edited: string;
}

/** Một nguồn của khung đối chiếu 4 cột. `status`: `missing` (chưa có gì),
    `partial` (chỉ còn baseline/snapshot), `ready` (đủ nội dung). `edited` là
    metadata lần AI biên tập cuối (dict `local_mt_ai_edited`) hoặc voucher cũ
    `before_rewrite`. */
export interface ChapterSource {
  status: "ready" | "partial" | "missing";
  text: string;
  title: string | null;
  revision: number | null;
  character_count: number;
  edited: Record<string, unknown> | null;
  engine: string | null;
  model: string | null;
  updated_at: string | null;
}

export interface AiRevision {
  id: number;
  engine: string;
  status: "pending" | "applied" | "discarded" | "expired";
  base_rev: number;
  base_translated_text: string;
  payload_json: string;
  payload_preview?: string;
  has_raw: boolean;
  created_at: string;
  expires_at: string;
}

export interface BranchState {
  label: string;
  has_text: boolean;
  revision: number;
  title: string;
  active: boolean;
}

export interface ChapterCompare {
  index: number;
  title: string;
  title_zh: string;
  url: string;
  skipped: boolean;
  has_raw: boolean;
  has_translated: boolean;
  has_mt_snapshot: boolean;
  /** Số phiên bản bản dịch — optimistic lock cho các thao tác ghi. */
  revision: number;
  /** Nhánh đang hoạt động — bản dịch của nhánh này là thứ đi vào EPUB. */
  active_branch: "ai" | "local_mt";
  branches: Record<"ai" | "local_mt", BranchState>;
  ai_revisions: AiRevision[];
  raw: string;
  translated: string;
  translated_mt: string;
  /** Bốn nguồn của khung đối chiếu: raw | local_mt | ai | ai_edit. */
  sources: Record<"raw" | "local_mt" | "ai" | "ai_edit", ChapterSource>;
  /** Chia theo DÒNG — khớp `para/save` và ghi chú. Dùng cho khung đọc/sửa. */
  translated_paras: string[];
  /** Chia theo KHỐI — chỉ để gióng các cột đối chiếu. KHÔNG dùng cho para/save. */
  paragraphs: Paragraph4[];
  raw_char_count: number;
  word_count: number;
  meta: Record<string, unknown>;
  prev_index: number | null;
  next_index: number | null;
  position: number;
  chapter_total: number;
}

export const ebookKey = (slug: string) => ["ebook", slug] as const;

export function useEbook(slug: string) {
  return useQuery({
    queryKey: ebookKey(slug),
    queryFn: () => api.get<EbookDetail>(`/api/ui/ebooks/${slug}`),
    enabled: Boolean(slug),
  });
}

export function useChapters(
  slug: string,
  filters: ChapterFilters,
  offset: number,
  limit: number,
) {
  // `show_zh_title` chỉ là cờ hiển thị phía client — không gửi lên API.
  const { show_zh_title: _zh, ...filterParams } = filters;
  void _zh;
  const params = new URLSearchParams({
    ...filterParams,
    offset: String(offset),
    limit: String(limit),
  });
  return useQuery({
    queryKey: ["chapters", slug, filters, offset, limit],
    queryFn: () => api.get<ChapterPage>(`/api/ui/ebooks/${slug}/chapters?${params}`),
    enabled: Boolean(slug),
    // Giữ trang cũ trong lúc tải trang mới: bảng không nháy trắng mỗi lần
    // đổi bộ lọc hay sang trang.
    placeholderData: keepPreviousData,
  });
}

export const chapterKey = (slug: string, index: number) => ["chapter", slug, index] as const;

/** Cỡ trang mặc định cho danh sách chương theo kiểu "cuộn để tải thêm". */
export const CHAPTERS_PAGE_SIZE = 100;

/**
 * Danh sách chương theo kiểu cuộn để tải thêm (infinite scroll).
 *
 * Dùng `useInfiniteQuery` TanStack v5 với API offset/limit hiện có. Query key
 * giữ tiền tố `["chapters", slug]` nên các lệnh invalidation đang có
 * (`lib/chapter.invalidateChapter` và `invalidateBookSearch`) vẫn làm mới danh
 * sách như trước — chỉ khác là `fetchNextPage` sẽ tải lại từ trang đầu.
 *
 * Lưu ý `getNextPageParam` so sánh với `matched` (số khớp bộ lọc), không phải
 * `total`, để không lãng phí một request thừa khi bộ lọc loại bớt chương.
 */
export function useInfiniteChapters(slug: string, filters: ChapterFilters, pageSize = CHAPTERS_PAGE_SIZE) {
  const { show_zh_title: _zh, ...filterParams } = filters;
  void _zh;
  const params = new URLSearchParams({
    ...filterParams,
    limit: String(pageSize),
  });
  return useInfiniteQuery({
    queryKey: ["chapters", slug, filters, pageSize],
    queryFn: ({ pageParam }) =>
      api.get<ChapterPage>(
        `/api/ui/ebooks/${slug}/chapters?${params.toString()}&offset=${String(pageParam)}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, p) => sum + p.rows.length, 0);
      return loaded < lastPage.matched ? loaded : undefined;
    },
    enabled: Boolean(slug),
    placeholderData: keepPreviousData,
  });
}

export function useChapter(slug: string, index: number) {
  return useQuery({
    queryKey: chapterKey(slug, index),
    queryFn: () => api.get<ChapterCompare>(`/api/ui/ebooks/${slug}/chapters/${index}`),
    enabled: Boolean(slug) && Number.isFinite(index),
  });
}

/** Trạng thái một chương, cùng thang màu với dải chương. */
export function rowTone(row: ChapterRow): "neutral" | "gold" | "indigo" | "celadon" {
  if (row.skipped) return "neutral";
  if (!row.has_translated) return row.has_raw ? "indigo" : "neutral";
  return row.bientap ? "celadon" : "gold";
}

/**
 * Số chương THẬT suy luận từ tiêu đề — ưu tiên tiêu đề dịch ("Chương 123: …",
 * cả "Quyển/Hồi"), fallback sang tiêu đề gốc ("第123章 …"). Trả null khi không
 * parse được số nào; dùng cho báo cáo khoảng trống index để phân biệt
 * "nguồn bỏ trống index" với "thiếu nội dung thật".
 */
export function chapterOrdinal(title: string, titleZh = ""): number | null {
  const vi = /(?:^|\s)(?:chương|chapter|ch\.?|quyển|hồi)\s*(\d+)\b/i.exec(title || "");
  if (vi) return Number(vi[1]);
  const zh = /^第\s*([\d]+)\s*(?:章|卷|回)/.exec((titleZh || "").trim());
  if (zh) return Number(zh[1]);
  return null;
}

/**
 * Nhãn trạng thái chính của một chương.
 *
 * Nói rõ bản dịch đến từ nhánh nào: trước đây chương nào đã dịch cũng đọc là
 * "Đã dịch máy" kể cả khi nhánh active là AI, nên cột trạng thái mâu thuẫn với
 * hai badge nhánh ngay bên cạnh.
 */
export function rowLabel(row: ChapterRow): string {
  if (row.skipped) return "Bỏ qua";
  if (!row.has_raw) return "Chưa crawl";
  if (!row.has_translated) return "Chưa dịch";
  if (row.bientap) return "Đã biên tập";
  return row.active_branch === "ai" ? "Đã dịch AI" : "Đã dịch máy";
}

/** Cảnh báo cần người xử lý tay, xếp theo mức độ khẩn. */
export function rowWarnings(row: ChapterRow): { key: string; label: string; hint: string }[] {
  const out: { key: string; label: string; hint: string }[] = [];
  if (row.duplicate_of !== null) {
    out.push({
      key: "duplicate",
      label: `Trùng #${row.duplicate_of}`,
      hint: `Cùng URL và tiêu đề với chương ${row.duplicate_of}.`,
    });
  }
  if (!row.title_format_ok) {
    out.push({
      key: "title",
      label: "Tiêu đề lỗi",
      hint: 'Tiêu đề sai mẫu "Chương N[: tên chương]" hoặc còn chữ Hán.',
    });
  }
  const missing = row.missing_fields.filter((field) => field !== "duplicate");
  if (missing.length > 0) {
    out.push({
      key: "missing",
      label: `Thiếu ${missing.join(", ")}`,
      hint: `Manifest thiếu trường: ${missing.join(", ")}.`,
    });
  }
  return out;
}

/* ── Hành động hàng loạt qua hợp đồng bulk-preview / bulk-confirm ──────
   Dịch (nhánh `ai`/`local_mt`) và biên tập AI (`ai-edit-draft`) bắt buộc
   preview trước rồi mới confirm; xem `components/chapter/BulkPreviewDialog`. */
