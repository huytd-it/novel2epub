import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface StorageReport {
  raw: number;
  translated: number;
  translated_mt: number;
  meta: number;
  glossary: number;
  epub: number;
  epub_exists: boolean;
  total: number;
  raw_chapters: number;
  translated_chapters: number;
  glossary_entries: number;
}

export interface StorageRow {
  slug: string;
  name: string;
  report: StorageReport;
}

export function useStorageOverview() {
  return useQuery({
    queryKey: ["storage"],
    queryFn: () => api.get<{ rows: StorageRow[]; grand_total: number }>("/api/ui/storage"),
  });
}

function useInvalidateStorage() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["storage"] });
}

export function usePurgeRaw() {
  const invalidate = useInvalidateStorage();
  return useMutation({
    mutationFn: (slug: string) => api.post<{ removed: number }>(`/api/ui/storage/${slug}/purge-raw`),
    onSuccess: invalidate,
  });
}

export function usePurgeMt() {
  const invalidate = useInvalidateStorage();
  return useMutation({
    mutationFn: (slug: string) => api.post<{ removed: number }>(`/api/ui/storage/${slug}/purge-mt`),
    onSuccess: invalidate,
  });
}

export function useRemoveEpub() {
  const invalidate = useInvalidateStorage();
  return useMutation({
    mutationFn: (slug: string) => api.post<{ removed: number }>(`/api/ui/storage/${slug}/remove-epub`),
    onSuccess: invalidate,
  });
}
