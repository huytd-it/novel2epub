import { useCallback, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface EbookSummary {
  slug: string;
  title: string;
  author: string;
  archived: boolean;
  in_library: boolean;
  toc_url: string;
  translate_type: string;
  created_at: string;
  updated_at: string;
  total: number;
  raw_count: number;
  translated_count: number;
  strip: string;
  counts: Record<string, number>;
  epub_exists: boolean;
  epub_size: number;
}

export interface LibraryResponse {
  ebooks: EbookSummary[];
  archived_count: number;
  total: number;
  page: number;
  limit: number;
  current: EbookSummary | null;
}

export interface LibraryQuery {
  showArchived?: boolean;
  q?: string;
  sort?: "title" | "title_desc" | "created_at" | "created_at_asc" | "updated_at" | "updated_at_asc" | "recent";
  page?: number;
  limit?: number;
  currentSlug?: string;
}

export function libraryKey(query: LibraryQuery = {}) {
  return ["library", query] as const;
}

export function useLibrary(query: LibraryQuery = {}) {
  const params = new URLSearchParams({
    show_archived: query.showArchived ? "1" : "0",
    q: query.q ?? "",
    sort: query.sort ?? "title",
    page: String(query.page ?? 0),
    limit: String(query.limit ?? 24),
  });
  if (query.currentSlug) params.set("current_slug", query.currentSlug);
  return useQuery({
    queryKey: libraryKey(query),
    queryFn: () =>
      api.get<LibraryResponse>(`/api/ui/library?${params}`),
  });
}

export interface CrawlPreview {
  chapter_link_pattern: string;
  content_selector: string;
  delay_seconds: number;
  scrapling_mode: string;
  solve_cloudflare: boolean;
  network_idle: boolean;
  proxy: string;
  strip_patterns: string[];
  [key: string]: unknown;
}

export interface EbookPreview {
  title: string;
  author: string;
  description: string;
  slug: string;
  cover_url: string;
  chapter_count: number;
  source: string;
  scrapling_mode: string;
  crawl_preview: CrawlPreview;
}

export interface CreateEbookInput {
  toc_url: string;
  slug?: string;
  title?: string;
  author?: string;
  description?: string;
  cover_url?: string;
  source?: string;
  scrapling_mode?: string;
  fetch_toc?: boolean;
}

export interface EbookCreateResult {
  status: "created";
  slug: string;
  title: string;
  source: string;
  toc_job: { job_id: string; category: string } | null;
}

export interface BulkEbookResult {
  url: string;
  status: "created" | "skipped-duplicate" | "failed";
  slug?: string;
  title?: string;
  source?: string;
  reason?: string;
  toc_job?: { job_id: string; category: string } | null;
}

export interface BulkPreviewResult {
  url: string;
  status: "ok" | "failed";
  reason?: string;
  title?: string;
  author?: string;
  description?: string;
  slug?: string;
  cover_url?: string;
  chapter_count?: number;
  source?: string;
  scrapling_mode?: string;
  crawl_preview?: CrawlPreview;
  [key: string]: unknown;
}

export interface BulkCreateItem {
  url: string;
  slug?: string;
  title?: string;
  author?: string;
  description?: string;
  cover_url?: string;
  source?: string;
  scrapling_mode?: string;
}

export interface TranslateMetaResult {
  title: string;
  author: string;
  description: string;
  subjects: string[];
  engine: string;
  model: string;
  source_language: string;
  errors: Record<string, string>;
}

function useInvalidateLibrary() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["library"] });
}

export function usePreviewEbook() {
  return useMutation({
    mutationFn: (input: Pick<CreateEbookInput, "toc_url" | "source" | "scrapling_mode">) =>
      api.post<EbookPreview>("/api/ui/library/ebooks/preview", { body: input }),
  });
}

export function useCreateEbook() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (input: CreateEbookInput) =>
      api.post<EbookCreateResult>("/api/ui/library/ebooks", { body: input }),
    onSuccess: invalidate,
  });
}

export function useCreateEbooksBulk() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (input: { toc_urls: string[]; items?: BulkCreateItem[]; fetch_toc?: boolean }) =>
      api.post<{ results: BulkEbookResult[] }>("/api/ui/library/ebooks/bulk", { body: input }),
    onSuccess: invalidate,
  });
}

/** Xóa vĩnh viễn ebook: EPUB + mọi dữ liệu đã crawl/dịch trong DB. */
export function useDeleteEbook() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (slug: string) =>
      api.post<{ ok: boolean }>(
        `/api/ui/library/ebooks/${encodeURIComponent(slug)}/delete`,
        { form: { confirm_slug: slug } },
      ),
    onSuccess: invalidate,
  });
}

export function usePreviewEbooksBulk() {
  return useMutation({
    mutationFn: (input: { toc_urls: string[] }) =>
      api.post<{ results: BulkPreviewResult[] }>("/api/ui/library/ebooks/bulk-preview", { body: input }),
  });
}

export function useTranslateMetadata() {
  return useMutation({
    mutationFn: (input: { title?: string; author?: string; description?: string; engine?: "localmt" | "ai"; model?: string }) =>
      api.post<TranslateMetaResult>("/api/ui/library/ebooks/translate-metadata", { body: input }),
  });
}

/* ── Truyện đang làm việc ────────────────────────────────────────────────
   Phần lớn công việc trong app diễn ra BÊN TRONG một truyện (chương, glossary,
   nhân vật, cài đặt, đọc). Giữ lựa chọn này ở một chỗ để thanh điều hướng mở
   thẳng vào truyện đó thay vì bắt quay lại Thư viện mỗi lần.                */

const BOOK_KEY = "n2e-current-book";
const listeners = new Set<() => void>();

function currentSlug(): string {
  return localStorage.getItem(BOOK_KEY) ?? "";
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useCurrentBook(): [string, (slug: string) => void] {
  const slug = useSyncExternalStore(subscribe, currentSlug, () => "");
  const select = useCallback((next: string) => {
    if (next) localStorage.setItem(BOOK_KEY, next);
    else localStorage.removeItem(BOOK_KEY);
    listeners.forEach((fn) => fn());
  }, []);
  return [slug, select];
}
