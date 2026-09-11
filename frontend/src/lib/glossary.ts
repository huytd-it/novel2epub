import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface GlossaryEntry {
  source: string;
  target: string;
  note: string;
}

export interface GlossaryPage {
  entries: GlossaryEntry[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface GlossaryQuery {
  page: number;
  per_page: number;
  q: string;
  sort: string;
  dir: string;
  /** Các cờ "giá trị đáng ngờ" đang bật, ngăn cách bởi dấu phẩy (OR). */
  filter: string;
}

/** Một chip lọc: cờ + số mục dính cờ đó trên toàn glossary. */
export interface GlossaryFlag {
  key: string;
  label: string;
  hint: string;
  count: number;
}

export interface PendingEntry {
  source: string;
  target: string;
  note: string;
  existing_target: string;
  count?: number;
  chapters?: number;
}

/** Một dòng bảng đã sửa nhưng chưa ghi (bản nháp chờ bấm "Áp dụng"). */
export interface GlossaryEdit {
  source: string;
  target: string;
  note: string;
  originalSource: string;
}

export type GlossaryEditKind = "new" | "update" | "rename" | "unchanged";

/** Một dòng trong modal xem trước: giá trị cũ + loại thay đổi + ảnh hưởng. */
export interface GlossaryEditPlan {
  source: string;
  target: string;
  note: string;
  original_source: string;
  existing_source: string;
  existing_target: string;
  existing_note: string;
  kind: GlossaryEditKind;
  error: string;
  /** Số chỗ trong bản dịch cũ sẽ đổi theo target mới. */
  count: number;
  chapters: number;
}

export interface GlossaryEditPreview {
  entries: GlossaryEditPlan[];
  writes: number;
  errors: number;
  total_matches: number;
}

export interface GlossaryEditResult {
  applied: number;
  added: number;
  renamed: number;
  skipped: number;
  replacements: { total: number; chapters: number; ebook: boolean };
}

export interface Suspects {
  same_target: { target: string; entries: GlossaryEntry[] }[];
  nested_source: { outer: GlossaryEntry; inner: GlossaryEntry }[];
  conflicts: { source: string; kept: string; new: string }[];
  count: number;
}

const listKey = (slug: string, query: GlossaryQuery) => ["glossary", slug, query] as const;
const pendingKey = (slug: string) => ["glossary-pending", slug] as const;

export function useGlossary(slug: string, query: GlossaryQuery) {
  const params = new URLSearchParams({
    page: String(query.page),
    per_page: String(query.per_page),
    q: query.q,
    sort: query.sort,
    dir: query.dir,
    filter: query.filter,
  });
  return useQuery({
    queryKey: listKey(slug, query),
    queryFn: () => api.get<GlossaryPage>(`/api/ebooks/${slug}/glossary/list?${params}`),
    enabled: Boolean(slug),
    placeholderData: (prev) => prev,
  });
}

/** Đề xuất chờ duyệt kèm số lần khớp trong bản dịch cũ (preview của propagate). */
export function usePendingGlossary(slug: string) {
  return useQuery({
    queryKey: pendingKey(slug),
    queryFn: () => api.get<{ entries: PendingEntry[]; count: number }>(
      `/api/ebooks/${slug}/glossary/replace/preview`,
    ),
    enabled: Boolean(slug),
  });
}

/** Bộ đếm cho các chip Lọc — cùng vị từ với bộ lọc nên số luôn khớp. */
export function useGlossaryFlags(slug: string) {
  return useQuery({
    queryKey: ["glossary-flags", slug],
    queryFn: () => api.get<{ flags: GlossaryFlag[]; total: number }>(`/api/ebooks/${slug}/glossary/flags`),
    enabled: Boolean(slug),
  });
}

export function useGlossarySuspects(slug: string, enabled: boolean) {
  return useQuery({
    queryKey: ["glossary-suspects", slug],
    queryFn: () => api.get<Suspects>(`/api/ebooks/${slug}/glossary/suspects`),
    enabled: Boolean(slug) && enabled,
  });
}

function useInvalidateGlossary(slug: string) {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: ["glossary", slug] });
    client.invalidateQueries({ queryKey: ["glossary-suspects", slug] });
    client.invalidateQueries({ queryKey: ["glossary-flags", slug] });
  };
}

export function useUpsertGlossaryEntry(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: (vars: GlossaryEntry & { originalSource: string }) =>
      api.post<{ ok: boolean }>(`/api/ebooks/${slug}/glossary/entry`, {
        form: {
          source: vars.source,
          target: vars.target,
          note: vars.note,
          original_source: vars.originalSource,
        },
      }),
    onSuccess: invalidate,
  });
}

const editBody = (edits: GlossaryEdit[]) => ({
  edits: edits.map((e) => ({
    source: e.source,
    target: e.target,
    note: e.note,
    original_source: e.originalSource,
  })),
});

/** Xem trước CẢ ĐỢT sửa (chỉ đọc) — nguồn dữ liệu cho modal "Áp dụng". */
export function usePreviewGlossaryEdits(slug: string) {
  return useMutation({
    mutationFn: (edits: GlossaryEdit[]) =>
      api.post<GlossaryEditPreview>(`/api/ebooks/${slug}/glossary/entries/preview`, {
        body: editBody(edits),
      }),
  });
}

/** Ghi cả đợt sau khi xác nhận: server từ chối toàn bộ nếu còn dòng lỗi. */
export function useApplyGlossaryEdits(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: (edits: GlossaryEdit[]) =>
      api.post<GlossaryEditResult>(`/api/ebooks/${slug}/glossary/entries`, { body: editBody(edits) }),
    onSuccess: invalidate,
  });
}

export function useDeleteGlossaryEntry(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: (source: string) =>
      api.post<{ ok: boolean }>(`/api/ebooks/${slug}/glossary/entry/delete`, { form: { source } }),
    onSuccess: invalidate,
  });
}

export function useDeleteGlossaryEntries(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: (sources: string[]) =>
      api.post<{ deleted: number }>(`/api/ebooks/${slug}/glossary/entries/delete`, { body: { sources } }),
    onSuccess: invalidate,
  });
}

export function useCleanGlossary(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: () =>
      api.post<{ before: number; after: number; removed: number }>(`/api/ebooks/${slug}/glossary/clean`),
    onSuccess: invalidate,
  });
}

export function useExportGlossary(slug: string) {
  return useMutation({
    mutationFn: () => api.post<{ text: string; count: number }>(`/api/ebooks/${slug}/glossary/export`),
  });
}

export function useImportGlossary(slug: string) {
  const invalidate = useInvalidateGlossary(slug);
  return useMutation({
    mutationFn: (text: string) =>
      api.post<{ added: number; updated: number; total: number }>(
        `/api/ebooks/${slug}/glossary/import`,
        { form: { text } },
      ),
    onSuccess: invalidate,
  });
}

/** Duyệt đề xuất: enqueue MỘT job (category=translate, khoá ebook) — không đổi
 * dữ liệu ngay, kết quả nằm trong log/outcome của job ở trang Hàng đợi. */
export function useApprovePending(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entries: { source: string; target: string; note: string }[]) =>
      api.post<{ started: boolean; requested: number }>(
        `/api/ebooks/${slug}/glossary/replace/approve`,
        { body: { entries } },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: pendingKey(slug) });
      client.invalidateQueries({ queryKey: ["queue"] });
    },
  });
}

/** Trợ lý AI: nhờ AI dịch lại các mục đã chọn. Enqueue MỘT job nền — kết quả
 * vào hàng chờ duyệt, KHÔNG ghi thẳng vào glossary. */
export function useGlossaryAiRetranslate(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { sources: string[]; instruction: string }) =>
      api.post<{ started: boolean; requested: number }>(
        `/api/ebooks/${slug}/glossary/ai/retranslate`,
        { body: vars },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ["queue"] }),
  });
}

export function useClearPending(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (vars: { sources?: string[]; all?: boolean }) =>
      api.post<{ cleared: number }>(`/api/ebooks/${slug}/glossary/pending/clear`, {
        body: vars.all ? { all: true } : { sources: vars.sources },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: pendingKey(slug) }),
  });
}
