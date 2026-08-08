import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface IdiomEntry {
  source: string;
  target: string;
  literals: string;
  protect: boolean;
}

export interface IdiomPage {
  entries: IdiomEntry[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface IdiomQuery {
  page: number;
  per_page: number;
  q: string;
  sort: string;
  dir: string;
}

const key = (query: IdiomQuery) => ["idioms", query] as const;

export function useIdioms(query: IdiomQuery) {
  const params = new URLSearchParams({
    page: String(query.page),
    per_page: String(query.per_page),
    q: query.q,
    sort: query.sort,
    dir: query.dir,
  });
  return useQuery({
    queryKey: key(query),
    queryFn: () => api.get<IdiomPage>(`/api/idioms/list?${params}`),
    placeholderData: (prev) => prev,
  });
}

function useInvalidateIdioms() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["idioms"] });
}

export function useUpsertIdiom() {
  const invalidate = useInvalidateIdioms();
  return useMutation({
    mutationFn: (vars: IdiomEntry & { originalSource: string }) =>
      api.post<{ ok: boolean }>("/api/idioms/entry", {
        form: {
          source: vars.source,
          target: vars.target,
          literals: vars.literals,
          protect: vars.protect ? "1" : "",
          original_source: vars.originalSource,
        },
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteIdiom() {
  const invalidate = useInvalidateIdioms();
  return useMutation({
    mutationFn: (source: string) =>
      api.post<{ ok: boolean }>("/api/idioms/entry/delete", { form: { source } }),
    onSuccess: invalidate,
  });
}

export function useDeleteIdioms() {
  const invalidate = useInvalidateIdioms();
  return useMutation({
    mutationFn: (sources: string[]) =>
      api.post<{ deleted: number }>("/api/idioms/entries/delete", { body: { sources } }),
    onSuccess: invalidate,
  });
}

export function useSeedIdioms() {
  const invalidate = useInvalidateIdioms();
  return useMutation({
    mutationFn: () => api.post<{ seeded: number }>("/api/idioms/seed"),
    onSuccess: invalidate,
  });
}

export function useExportIdioms() {
  return useMutation({
    mutationFn: () => api.post<{ text: string; count: number }>("/api/idioms/export"),
  });
}

export function useImportIdioms() {
  const invalidate = useInvalidateIdioms();
  return useMutation({
    mutationFn: (text: string) =>
      api.post<{ added: number; updated: number }>("/api/idioms/import", { form: { text } }),
    onSuccess: invalidate,
  });
}
