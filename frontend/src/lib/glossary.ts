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
}

export interface PendingEntry {
  source: string;
  target: string;
  note: string;
  existing_target: string;
  count?: number;
  chapters?: number;
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
