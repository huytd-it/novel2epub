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
  url: string;
  has_raw: boolean;
  has_translated: boolean;
  missing_fields: string[];
  duplicate_of: number | null;
  last_action_status: string;
  word_count: number;
  zh_char_count: number;
  bientap: string;
  bientap_tooltip: string;
  skipped: boolean;
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
  filter_translated: string;
  filter_missing: string;
  filter_skipped: string;
}

export const DEFAULT_FILTERS: ChapterFilters = {
  search: "",
  sort: "source",
  direction: "asc",
  filter_raw: "any",
  filter_translated: "any",
  filter_missing: "any",
  filter_skipped: "any",
};

export interface Paragraph {
  raw: string;
  mt: string;
  edited: string;
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
  /** Chia theo DÒNG — khớp `para/save` và ghi chú. Dùng cho khung đọc/sửa. */
  translated_paras: string[];
  /** Chia theo KHỐI — chỉ để gióng 3 cột đối chiếu. KHÔNG dùng cho para/save. */
  paragraphs: Paragraph[];
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
  const params = new URLSearchParams({
    ...filters,
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
  const params = new URLSearchParams({
    ...filters,
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

export function rowLabel(row: ChapterRow): string {
  if (row.skipped) return "Bỏ qua";
  if (!row.has_raw) return "Chưa crawl";
  if (!row.has_translated) return "Có bản gốc";
  return row.bientap ? "Đã biên tập" : "Đã dịch máy";
}

/* ── Hành động hàng loạt qua hợp đồng bulk-preview / bulk-confirm ──────
   Dịch (nhánh `ai`/`local_mt`) và biên tập AI (`ai-edit-draft`) bắt buộc
   preview trước rồi mới confirm; xem `components/chapter/BulkPreviewDialog`. */
